#!/usr/bin/env python3
"""T-B140c 离线装载：把已校验的日线历史行变成幂等 INSERT，不连真实库、不读证书、不出网。

口径出处：
- 接口字段 t/o/h/l/c/v/a/pc/sf：T003-mairui-capability.md §2（日线字段）。
- v 单位为手、a 为元、n 为不复权：T003 GAP2 / T-B05-recheck.md「日线 v 同样是手」/ T-A136「v(手)」。
- 库内 volume 为股：daily-bars-tdx 契约「两侧均为股」，故 volume = v × 100。
- 主键 (code, trade_date, adj_type)，ON CONFLICT DO NOTHING：app/db/tables/market.py。
- active 证书判定对齐 owned_daily_read._licence（status=active、未删除、未暂停、未过期、无 hold）。
- 契约 §10.12 第 1 条：可信材料未落地，生产 BJ 阻断；自填对照不构成许可。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from psycopg import Connection as PsycopgConnection
from sqlalchemy.dialects.postgresql import dialect

from app.bj_offline_volume import (
    CodeReject, RowReject, _QUALIFIED_RE, _bj_write_unconfirmed, _is_suspended,
    _trade_date, confirm_bj_offline_volume_units, market_of, qualified_code,
)
from app.marketdata.daily_bars import (
    DailyBar, DailyBarsResult, daily_bar_write_allowed, upsert_daily_bars,
)

HIST_ST = date(2023, 11, 13)
HIST_ET = date(2026, 11, 13)
ADJ_TYPE = "none"
SOURCE = "mairui"
APPLY_PAYLOAD_PREFIX = "-- tb140_apply_payload="
VOL_MULT = 100  # 手 → 股

def parse_window(
    st: str | date | None = None, et: str | date | None = None,
) -> tuple[date | None, date | None]:
    """CLI 日期只接受 YYYYMMDD；内部允许 date，缺省不补边界。"""
    def parse(value: str | date | None) -> date | None:
        if value is None:
            return None
        if type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{8}", value):
            raise RowReject("window_date_invalid")
        try:
            return date(int(value[:4]), int(value[4:6]), int(value[6:]))
        except ValueError:
            raise RowReject("window_date_invalid") from None

    start, end = parse(st), parse(et)
    if start is not None and end is not None and start > end:
        raise RowReject("window_start_after_end")
    return start, end


def requestable_history_codes(codes: Sequence[str]) -> tuple[list[str], list[dict[str, str]]]:
    """所有回填入口共用：识别 BJ 旧码但不请求、不推算新码。"""
    accepted, skipped = [], []
    for value in codes:
        code = value.strip()
        market = market_of(code)
        if market == "BJ" and not code.startswith("920"):
            skipped.append({"code": code, "reason": "旧码不请求"})
        else:
            accepted.append(code)
    return accepted, skipped


def plan_history_expansion(
    ledger: Mapping[str, Any], *, ledger_path: str | Path | None = None,
    st: str | date | None = None, et: str | date | None = None,
) -> dict[str, Any]:
    """只规划扩窗待补；不改原账本、计数或 HALT，不发请求。"""
    start, end = parse_window(st, et)
    window = ledger.get("window")
    windows = ledger.get("history_windows")
    if not isinstance(windows, Mapping):
        windows = {}
    pending = []
    if start is None and end is None:
        for code in ledger.get("done_history") or []:
            recorded = windows.get(code, window)
            if not isinstance(recorded, dict) or any(
                key not in recorded or recorded[key] is not None for key in ("st", "et")
            ):
                pending.append(code)
    return {
        "original_ledger": str(ledger_path) if ledger_path is not None else None,
        "original_window": dict(window) if isinstance(window, dict) else None,
        "window": {"st": start.isoformat() if start else None, "et": end.isoformat() if end else None},
        "pending": [{"code": code, "reason": "旧窗口待补：old_window_not_complete"} for code in pending],
        "pending_codes": pending,
        "auto_request": False,
    }


def _decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise RowReject(f"field_invalid:{name}")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise RowReject(f"field_invalid:{name}") from exc
    if not number.is_finite():
        raise RowReject(f"field_invalid:{name}")
    return number


def _identity_ok(row: dict[str, Any], expected: str) -> None:
    for key in ("code", "dm", "symbol", "secu_code", "security"):
        if key not in row:
            continue
        raw = str(row[key]).strip().upper().replace(" ", "")
        if not raw:
            continue
        expect_num, expect_mkt = expected.split(".")
        compact = raw.replace(".", "")
        if raw in {expected, expect_num}:
            continue
        if compact == expect_num + expect_mkt:
            continue
        raise RowReject("identity_mismatch")


def validate_bar(row: Any, expected_code: str, *, st: date | None = None, et: date | None = None) -> dict[str, Any] | None:
    """通过则返回可入库行；日期越界返回 None（跳过、不伪造）；其余抛 RowReject。"""
    if not _QUALIFIED_RE.fullmatch(expected_code):
        raise CodeReject("qualified_code_invalid")
    if not isinstance(row, dict):
        raise RowReject("row_not_object")
    _identity_ok(row, expected_code)
    day = _trade_date(row.get("t"))
    st, et = parse_window(st, et)
    if (st is not None and day < st) or (et is not None and day > et):
        return None
    open_ = _decimal(row.get("o"), "o")
    high = _decimal(row.get("h"), "h")
    low = _decimal(row.get("l"), "l")
    close = _decimal(row.get("c"), "c")
    volume_hands = _decimal(row.get("v"), "v")
    amount = _decimal(row.get("a"), "a")
    if min(open_, high, low, close) <= 0:
        raise RowReject("ohlc_not_positive")
    if high < low or high < open_ or high < close or low > open_ or low > close:
        raise RowReject("ohlc_inconsistent")
    if volume_hands < 0 or amount < 0:
        raise RowReject("volume_or_amount_negative")
    shares = volume_hands * VOL_MULT
    if shares != shares.to_integral_value():
        raise RowReject("volume_not_integer_shares")
    pre_close = None
    if row.get("pc") is not None and row.get("pc") != "":
        pre_close = _decimal(row.get("pc"), "pc")
        if pre_close <= 0:
            raise RowReject("pre_close_not_positive")
    return {
        "code": expected_code,
        "trade_date": day.isoformat(),
        "adj_type": ADJ_TYPE,
        "open": _num(open_),
        "high": _num(high),
        "low": _num(low),
        "close": _num(close),
        "pre_close": None if pre_close is None else _num(pre_close),
        "volume": int(shares),
        "amount": _num(amount),
        "is_suspended": _is_suspended(row.get("sf")),
        "source": SOURCE,
    }


def normalize_history(
    code: str,
    body: Any,
    *,
    st: date | None = None,
    et: date | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """只接受 list body。返回 (rows, rejects)。不编造缺日。"""
    st, et = parse_window(st, et)
    expected = qualified_code(code)
    if not isinstance(body, list):
        raise RowReject("history_body_not_list")
    rows: list[dict[str, Any]] = []
    rejects: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(body):
        try:
            bar = validate_bar(item, expected, st=st, et=et)
        except (RowReject, CodeReject) as exc:
            rejects.append({"index": str(index), "reason": str(exc)})
            continue
        if bar is None:
            rejects.append({"index": str(index), "reason": "date_out_of_window"})
            continue
        key = (bar["code"], bar["trade_date"], bar["adj_type"])
        if key in seen:
            rejects.append({"index": str(index), "reason": "duplicate_pk"})
            continue
        seen.add(key)
        rows.append(bar)
    rows.sort(key=lambda r: r["trade_date"])
    return rows, rejects


def resolve_active_licence(candidates: Sequence[Any]) -> tuple[str | None, str]:
    """离线裁定 active 证书 id。0 条 → NULL 并 pending_bind；多条 → NULL 并不猜。"""
    ids: list[str] = []
    for item in candidates:
        if item in (None, ""):
            continue
        try:
            ids.append(str(uuid.UUID(str(item))))
        except (ValueError, AttributeError, TypeError):
            return None, "pending_bind_invalid_id"
    unique = list(dict.fromkeys(ids))
    if not unique:
        return None, "pending_bind"
    if len(unique) > 1:
        return None, "pending_bind_ambiguous"
    return unique[0], "bound"


ACTIVE_LICENCE_SQL = """
SELECT s.id
FROM app.user_data_licence_status AS s
LEFT JOIN app.user_data_licence_holds AS h ON h.user_id = s.user_id
WHERE s.deleted_at IS NULL
  AND s.status = 'active'
  AND COALESCE(s.provider, 'mairui') = 'mairui'
  AND (s.paused_until IS NULL OR s.paused_until <= now())
  AND (s.expires_on IS NULL OR s.expires_on >= (now() AT TIME ZONE 'Asia/Shanghai')::date)
  AND h.user_id IS NULL
""".strip()


def _num(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if not re.fullmatch(r"[0-9A-Za-z_+\-.:]+", text):
        raise RowReject("sql_literal_rejected")
    return "'" + text + "'"


def render_insert_sql(
    rows: Iterable[dict[str, Any]],
    licence_id: str | None,
    *,
    bind_note: str,
) -> str:
    """生成临时 staging 与 JSON 数据载荷，不携带目标表 DML 或持久化许可。

    目标表只能通过 apply_insert_artifact 在消费进程内重新检查门闩后写入。
    """
    bind_note = " ".join(bind_note.splitlines())
    material = list(rows)
    for row in material:
        row_insert_params(row, licence_id)
    writable = [row for row in material if daily_bar_write_allowed(str(row["code"]))]
    blocked_bj = len(material) - len(writable)
    blocked_note = (
        f"-- BJ INSERT blocked: bj_offline_volume_units_unconfirmed ({blocked_bj} rows); "
        "契约 §10.12 第 1 条：可信材料未落地，生产 BJ 阻断。\n"
    ) if blocked_bj else ""
    payload = json.dumps({"bars": material, "licence_id": licence_id}, ensure_ascii=False, default=str)
    material = writable
    lines = [
        "-- T-B140c artifact: apply_insert_artifact uses audited conditional replacement.",
        "-- Direct psql execution stages data only; it never writes market.daily_bars.",
        APPLY_PAYLOAD_PREFIX + payload,
        f"-- bind_note={bind_note}",
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        "CREATE TEMP TABLE tb140_daily_bars_stage (LIKE market.daily_bars INCLUDING ALL) ON COMMIT DROP;",
    ]
    if not material:
        lines.extend(["-- no rows", "COMMIT;"])
        return blocked_note + "\n".join(lines) + "\n"
    cols = (
        "code,trade_date,adj_type,open,high,low,close,pre_close,"
        "volume,amount,is_suspended,source,source_licence_id"
    )
    lines.append(f"INSERT INTO pg_temp.tb140_daily_bars_stage ({cols}) VALUES")
    values: list[str] = []
    lic = "NULL"
    if licence_id is not None:
        lic = "'" + str(uuid.UUID(licence_id)) + "'::uuid"
    for row in material:
        if row.get("source") != SOURCE or row.get("adj_type") != ADJ_TYPE:
            raise RowReject("source_or_adj_forged")
        if not _QUALIFIED_RE.fullmatch(str(row["code"])):
            raise RowReject("qualified_code_invalid")
        parts = [
            _sql_literal(row["code"]),
            _sql_literal(row["trade_date"]),
            _sql_literal(ADJ_TYPE),
            _sql_literal(row["open"]),
            _sql_literal(row["high"]),
            _sql_literal(row["low"]),
            _sql_literal(row["close"]),
            _sql_literal(row["pre_close"]),
            _sql_literal(int(row["volume"])),
            _sql_literal(row["amount"]),
            _sql_literal(bool(row["is_suspended"])),
            _sql_literal(SOURCE),
            lic,
        ]
        values.append("(" + ",".join(parts) + ")")
    lines.append(",\n".join(values))
    lines.append("ON CONFLICT (code, trade_date, adj_type) DO NOTHING;")
    if licence_id is None:
        lines.append(f"-- pending bind: {bind_note}; source_licence_id is NULL")
    lines.append("COMMIT;")
    return blocked_note + "\n".join(lines) + "\n"


def apply_insert_offline(
    existing: set[tuple[str, str, str]],
    rows: Sequence[dict[str, Any]],
) -> dict[str, int]:
    """内存模拟 ON CONFLICT DO NOTHING，不连库。

    未确认 BJ 行不进入模拟表，返回 blocked_bj_unconfirmed 计数；沪深行照常处理。
    """
    table = set(existing)
    inserted = 0
    skipped = 0
    blocked_bj = 0
    for row in rows:
        if row.get("source") != SOURCE or row.get("adj_type") != ADJ_TYPE:
            raise RowReject("source_or_adj_forged")
        row_insert_params(row, None)
        if not daily_bar_write_allowed(str(row["code"])):
            blocked_bj += 1
            continue
        key = (str(row["code"]), str(row["trade_date"]), ADJ_TYPE)
        if key in table:
            skipped += 1
            continue
        table.add(key)
        inserted += 1
    result = {"inserted": inserted, "skipped_existing": skipped, "total": len(table)}
    if blocked_bj:
        result["blocked_bj_unconfirmed"] = blocked_bj
    return result


def write_normalized(
    path: Path, code: str, rows: Sequence[dict[str, Any]], rejects: Sequence[dict[str, str]],
    *, st: date | None = None, et: date | None = None,
) -> None:
    st, et = parse_window(st, et)
    payload = {
        "code": qualified_code(code),
        "window": {"st": st.isoformat() if st else None, "et": et.isoformat() if et else None},
        "adj_type": ADJ_TYPE,
        "source": SOURCE,
        "n": len(rows),
        "reject_n": len(rejects),
        "rejects": list(rejects),
        "bars": list(rows),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def load_normalized(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("source") != SOURCE or payload.get("adj_type") != ADJ_TYPE:
        raise RowReject("source_or_adj_forged")
    expected = str(payload.get("code", ""))
    window = payload.get("window") or {}
    try:
        st = date.fromisoformat(window["st"]) if window.get("st") is not None else None
        et = date.fromisoformat(window["et"]) if window.get("et") is not None else None
    except (TypeError, ValueError):
        raise RowReject("window_date_invalid") from None
    rows, _ = normalize_history(
        expected.split(".")[0],
        [
            {
                "t": r["trade_date"],
                "o": r["open"],
                "h": r["high"],
                "l": r["low"],
                "c": r["close"],
                "v": Decimal(str(r["volume"])) / VOL_MULT,
                "a": r["amount"],
                "pc": r.get("pre_close"),
                "sf": 1 if r.get("is_suspended") else 0,
                "code": r["code"],
            }
            for r in payload.get("bars", [])
        ],
        st=st, et=et,
    )
    for row in rows:
        if row["code"] != expected:
            raise RowReject("identity_mismatch")
    return rows


COUNT_DAILY_BARS_SQL = "SELECT count(*) FROM market.daily_bars"


def to_psycopg_dsn(url: str) -> str:
    """把 SQLAlchemy 风格 ``postgresql+psycopg://`` 转成 psycopg 可用的 ``postgresql://``。

    算法出处：``src/backend/app/api/v1/health.py`` 的 ``_psycopg_dsn``。
    不打印、不记录传入值。
    """
    if not isinstance(url, str) or not url.strip():
        raise RowReject("db_url_invalid")
    scheme, sep, rest = url.partition("://")
    if sep and "+" in scheme:
        scheme = scheme.split("+", 1)[0]
    return f"{scheme}{sep}{rest}"


def row_insert_params(row: dict[str, Any], licence_id: str | None) -> tuple[Any, ...]:
    """生成参数化 INSERT 的一组参数；licence_id 缺省为 NULL。"""
    if row.get("source") != SOURCE or row.get("adj_type") != ADJ_TYPE:
        raise RowReject("source_or_adj_forged")
    if not _QUALIFIED_RE.fullmatch(str(row["code"])):
        raise RowReject("qualified_code_invalid")
    # 公共写入入口也拒绝伪造后缀、非法字段与非整数股数，不能只依赖上游校验。
    raw = {
        "code": row["code"], "t": row["trade_date"],
        "o": row["open"], "h": row["high"], "l": row["low"], "c": row["close"],
        "pc": row.get("pre_close"), "v": _decimal(row["volume"], "volume") / VOL_MULT,
        "a": row["amount"], "sf": row["is_suspended"],
    }
    validate_bar(raw, qualified_code(str(row["code"]).split(".")[0]))
    lic: str | None
    if licence_id is None:
        lic = None
    else:
        lic = str(uuid.UUID(str(licence_id)))
    return (
        row["code"],
        row["trade_date"],
        ADJ_TYPE,
        row["open"],
        row["high"],
        row["low"],
        row["close"],
        row["pre_close"],
        int(row["volume"]),
        row["amount"],
        bool(row["is_suspended"]),
        SOURCE,
        lic,
    )


def jsonl_reconcile_sink(path: Path) -> Callable[[dict[str, Any]], None]:
    """每条记录追加、flush 到磁盘后才返回；失败向事务边界传播。"""
    path = path.resolve()
    def sink(record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return sink


class _WriterConnection:
    """在调用方的 psycopg 事务上执行公共 writer 的 SQLAlchemy 语句；不拥有连接。"""

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def execute(self, statement: Any) -> Any:
        compiled = statement.compile(dialect=dialect(), compile_kwargs={"render_postcompile": True})
        with self.conn.cursor() as cursor:
            cursor.execute(str(compiled), compiled.params)
            names = [column.name for column in cursor.description] if cursor.description else []
            rows = [dict(zip(names, row)) if not isinstance(row, Mapping) else dict(row)
                    for row in cursor.fetchall()] if names else []
        return SimpleNamespace(all=lambda: [SimpleNamespace(**row) for row in rows],
                               mappings=lambda: rows)


def apply_daily_bars(
    conn: Any,
    rows: Sequence[dict[str, Any]],
    licence_id: str | None = None,
    *, reconcile_sink: Callable[[dict[str, Any]], None] | None = None,
    reconcile_path: Path = Path("tb140_history_reconcile.jsonl"),
) -> dict[str, int]:
    """通过公共 writer 写入；拥有事务并在提交/回滚后记录替换结果。"""
    material = [row_insert_params(row, licence_id) for row in rows]
    bars = [DailyBar(
        code=params[0], trade_date=date.fromisoformat(str(params[1])), adj_type=params[2],
        **{name: None if value is None else Decimal(str(value)) for name, value in
           zip(("open", "high", "low", "close", "pre_close", "volume", "amount"), params[3:10])},
        is_suspended=params[10],
    ) for params in material]
    sink = reconcile_sink or jsonl_reconcile_sink(reconcile_path)
    pending: dict[str, dict[str, Any]] = {}

    def audit(record: dict[str, Any]) -> None:
        if record["kind"] == "replace_result":
            record = dict(record, replace_result=record["value"],
                          existing_source="tdx_local", incoming_source=SOURCE)
        sink(record)
        identity = str(record["replacement_id"])
        if str(record["kind"]).startswith("replaced_tdx_local"):
            pending[identity] = {key: record[key] for key in
                                 ("replacement_id", "code", "trade_date", "adj_type")}
        elif record["kind"] == "replace_result":
            pending.pop(identity, None)

    status = getattr(getattr(conn, "info", None), "transaction_status", 0)
    if status is not None and int(status) != 0:
        raise RowReject("connection_transaction_already_active")
    tx = getattr(conn, "transaction", None)
    if not callable(tx):
        raise RowReject("connection_transaction_required")
    writer_conn = _WriterConnection(conn) if isinstance(conn, PsycopgConnection) else conn

    def count() -> int:
        with conn.cursor() as cur:
            cur.execute(COUNT_DAILY_BARS_SQL)
            fetched = cur.fetchone()
            return int(fetched[0]) if fetched is not None else 0

    try:
        with tx():
            before = count()
            stats = upsert_daily_bars(
                writer_conn, DailyBarsResult(bars=bars), source=SOURCE,
                licence_id=uuid.UUID(licence_id) if licence_id is not None else None,
                fetched_at=datetime.now(UTC), reconcile_sink=audit,
            )
            after = count()
    except BaseException as exc:
        try:
            for record in list(pending.values()):
                audit(dict(record, kind="replace_result", value="rolled_back"))
        except BaseException:
            exc.add_note("replace_result_write_failed")
        raise
    stats.reconcile_after_transaction(committed=True)
    result = {"count_before": before, "count_after": after, "inserted": stats.inserted}
    if stats.blocked_bj_unconfirmed:
        result["blocked_bj_unconfirmed"] = stats.blocked_bj_unconfirmed
    if stats.replaced or reconcile_sink is not None:
        result["replaced"] = stats.replaced
    return result


WRONG_SUFFIX_GROUP_SQL = """
SELECT code, source, adj_type, count(*) AS row_count,
       min(trade_date) AS first_date, max(trade_date) AS last_date
FROM market.daily_bars
WHERE code ~ '^920[0-9]{3}[.]SH$'
GROUP BY code, source, adj_type ORDER BY code, source, adj_type
""".strip()

WRONG_SUFFIX_COMPARE_SQL = """
SELECT bad.code, bad.source AS existing_source, target.source AS target_source,
       bad.adj_type,
       CASE WHEN target.code IS NULL THEN 'target_missing'
            WHEN ROW(bad.open, bad.high, bad.low, bad.close, bad.pre_close,
                     bad.volume, bad.amount, bad.is_suspended)
                 IS NOT DISTINCT FROM
                 ROW(target.open, target.high, target.low, target.close, target.pre_close,
                     target.volume, target.amount, target.is_suspended)
            THEN 'same_key_same_values' ELSE 'same_key_different_values' END AS category,
       count(*) AS row_count, min(bad.trade_date) AS first_date, max(bad.trade_date) AS last_date
FROM market.daily_bars AS bad
LEFT JOIN market.daily_bars AS target
  ON target.code = left(bad.code, 6) || '.BJ'
 AND target.trade_date = bad.trade_date AND target.adj_type = bad.adj_type
WHERE bad.code ~ '^920[0-9]{3}[.]SH$'
GROUP BY bad.code, bad.source, target.source, bad.adj_type, category
ORDER BY bad.code, bad.source, target.source, bad.adj_type, category
""".strip()


def wrong_suffix_stats(conn: Any) -> dict[str, list[Any]]:
    """在传入连接仅执行两条 SELECT；不提交、不回滚、不改连接或账本状态。"""
    with conn.cursor() as cur:
        cur.execute(WRONG_SUFFIX_GROUP_SQL)
        groups = list(cur.fetchall())
        cur.execute(WRONG_SUFFIX_COMPARE_SQL)
        comparison = list(cur.fetchall())
    return {"groups": groups, "comparison": comparison}


def apply_insert_artifact(
    conn: Any, path: Path, *, reconcile_path: Path | None = None,
) -> dict[str, int]:
    """只读取生成产物的 JSON 载荷，复用审计写入器；绝不直接执行文件中的 SQL。

    载荷不携带许可；旧文件中的 SQL 也不执行，消费时重新检查当前进程的门闩。
    默认对账文件放产物旁，避免依赖进程工作目录。
    """
    payloads = [line[len(APPLY_PAYLOAD_PREFIX):] for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith(APPLY_PAYLOAD_PREFIX)]
    if len(payloads) != 1:
        raise RowReject("artifact_payload_invalid")
    try:
        payload = json.loads(payloads[0])
    except json.JSONDecodeError:
        raise RowReject("artifact_payload_invalid") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("bars"), list):
        raise RowReject("artifact_payload_invalid")
    return apply_daily_bars(
        conn, payload["bars"], payload.get("licence_id"),
        reconcile_path=reconcile_path if reconcile_path is not None else path.with_suffix(".reconcile.jsonl"),
    )
