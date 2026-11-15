#!/usr/bin/env python3
"""T-B140c 离线装载：把已校验的日线历史行变成幂等 INSERT，不连真实库、不读证书、不出网。

口径出处：
- 接口字段 t/o/h/l/c/v/a/pc/sf：T003-mairui-capability.md §2（日线字段）。
- v 单位为手、a 为元、n 为不复权：T003 GAP2 / T-B05-recheck.md「日线 v 同样是手」/ T-A136「v(手)」。
- 库内 volume 为股：daily-bars-tdx 契约「两侧均为股」，故 volume = v × 100。
- 主键 (code, trade_date, adj_type)，ON CONFLICT DO NOTHING：app/db/tables/market.py。
- active 证书判定对齐 owned_daily_read._licence（status=active、未删除、未暂停、未过期、无 hold）。
- T-A158 第 5 项：BJ 写库前须 confirm_bj_offline_volume_units 离线对算至少 20 只。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from app.bj_offline_volume import (
    _QUALIFIED_RE,
    VOL_MULT,
    CodeReject,
    RowReject,
    _bj_write_unconfirmed,
    _decimal,
    _trade_date,
    qualified_code,
)
from app.bj_offline_volume import (
    confirm_bj_offline_volume_units as confirm_bj_offline_volume_units,
)
from app.bj_offline_volume import (
    market_of as market_of,
)

HIST_ST = date(2023, 11, 13)
HIST_ET = date(2026, 11, 13)
ADJ_TYPE = "none"
SOURCE = "mairui"
APPLY_PAYLOAD_PREFIX = "-- tb140_apply_payload="


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


def _is_suspended(value: Any) -> bool:
    return value in (1, "1", True, "true", "True")


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
    """生成非替换路径的幂等 INSERT；有 tdx 重叠时拒绝离线 SQL 执行。

    产物通过 apply_insert_artifact 读取载荷并复用 apply_daily_bars，支持受审计替换。
    直接用 psql 执行只允许非替换路径；重叠时必须走 Python 的持久化对账和事务后回执。
    licence_id 必须是已裁定值，不在渲染时查库。
    BJ 未经 confirm_bj_offline_volume_units 确认时只记录阻断注释，不生成其写入载荷
    或 SQL；混合批次中的沪深行仍可生成 INSERT。
    """
    material = list(rows)
    for row in material:
        row_insert_params(row, licence_id)
    writable = [row for row in material if not _bj_write_unconfirmed(row)]
    blocked_bj = len(material) - len(writable)
    blocked_note = (
        f"-- BJ INSERT blocked: bj_offline_volume_units_unconfirmed ({blocked_bj} rows); "
        "call confirm_bj_offline_volume_units first.\n"
    ) if blocked_bj else ""
    material = writable
    if blocked_bj and not material:
        return blocked_note
    payload = json.dumps({"bars": material, "licence_id": licence_id}, ensure_ascii=False, default=str)
    lookup = ACTIVE_LICENCE_SQL.replace("\n", "\n-- ")
    lines = [
        "-- T-B140c artifact: apply_insert_artifact uses audited conditional replacement.",
        "-- Direct psql execution only supports non-replacement INSERT ON CONFLICT DO NOTHING.",
        APPLY_PAYLOAD_PREFIX + payload,
        f"-- bind_note={bind_note}",
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        f"-- active licence lookup (apply-time, for operator check):\n-- {lookup}",
    ]
    if not material:
        lines.extend(["-- no rows", "COMMIT;"])
        return blocked_note + "\n".join(lines) + "\n"
    cols = (
        "code,trade_date,adj_type,open,high,low,close,pre_close,"
        "volume,amount,is_suspended,source,source_licence_id"
    )
    keys = ",\n".join(
        "(" + ",".join(_sql_literal(row[key]) for key in ("code", "trade_date", "adj_type")) + ")"
        for row in material
    )
    lines.extend([
        "-- Fail closed on replacement: use the audited Python writer for these keys.",
        "DO $tb149_guard$ BEGIN",
        "IF EXISTS (SELECT 1 FROM market.daily_bars AS b JOIN (VALUES",
        keys,
        ") AS incoming(code, trade_date, adj_type) ON b.code = incoming.code",
        "AND b.trade_date = incoming.trade_date::date AND b.adj_type = incoming.adj_type",
        "WHERE b.source = 'tdx_local') THEN",
        "RAISE EXCEPTION 'tdx_local overlap requires audited conditional UPDATE via apply_daily_bars';",
        "END IF; END $tb149_guard$;",
    ])
    lines.append(f"INSERT INTO market.daily_bars ({cols}) VALUES")
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
        if _bj_write_unconfirmed(row):
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


INSERT_DAILY_BARS_SQL = (
    "INSERT INTO market.daily_bars ("
    "code, trade_date, adj_type, open, high, low, close, pre_close, "
    "volume, amount, is_suspended, source, source_licence_id"
    ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (code, trade_date, adj_type) DO NOTHING"
)

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


# 来源与字段必须可证实；不能从计数推断已有行的来源。
SELECT_EXISTING_BAR_SQL = """
SELECT count(*) OVER () AS row_count, source, open, high, low, close, pre_close,
       volume, amount, is_suspended
FROM market.daily_bars WHERE code = %s AND trade_date = %s AND adj_type = %s
""".strip()

REPLACE_TDX_LOCAL_SQL = """
UPDATE market.daily_bars
SET open = %s, high = %s, low = %s, close = %s, pre_close = %s,
    volume = %s, amount = %s, is_suspended = %s, source = %s,
    source_licence_id = %s, fetched_at = now()
WHERE code = %s AND trade_date = %s AND adj_type = %s AND source = 'tdx_local'
""".strip()


def jsonl_reconcile_sink(path: Path) -> Callable[[dict[str, Any]], None]:
    """每条记录追加、flush 到磁盘后才返回；失败向事务边界传播。"""
    path = path.resolve()
    def sink(record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    return sink


def _replacement_records(old: Mapping[str, Any], row: Mapping[str, Any], replacement_id: str) -> list[dict[str, Any]]:
    common = {
        "replacement_id": replacement_id, "code": row["code"],
        "trade_date": str(row["trade_date"]), "adj_type": row["adj_type"], "ts": None,
        "existing_source": "tdx_local", "incoming_source": SOURCE,
    }
    records = []
    for field in ("open", "high", "low", "close", "pre_close", "volume", "amount", "is_suspended"):
        existing, incoming = old.get(field), row.get(field)
        tolerance = Decimal(0)
        if field != "is_suspended":
            existing = _decimal(existing, field) if existing is not None else None
            incoming = _decimal(incoming, field) if incoming is not None else None
            if field in ("open", "high", "low", "close", "pre_close"):
                existing = existing.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if existing is not None else None
                incoming = incoming.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if incoming is not None else None
            if field == "amount":
                tolerance = max(Decimal(1), abs(existing or Decimal(0)) * Decimal("2.4e-7"))
        same = existing == incoming
        if not same and field != "is_suspended" and existing is not None and incoming is not None:
            same = abs(existing - incoming) <= tolerance
        if not same:
            records.append(dict(common, kind="replaced_tdx_local", field=field,
                                existing_value=str(existing) if existing is not None else None,
                                incoming_value=str(incoming) if incoming is not None else None,
                                tolerance=str(tolerance)))
    return records or [dict(common, kind="replaced_tdx_local_same", field="*",
                            existing_value=dict(old), incoming_value=dict(row), tolerance="0")]


def apply_daily_bars(
    conn: Any,
    rows: Sequence[dict[str, Any]],
    licence_id: str | None = None,
    *, reconcile_sink: Callable[[dict[str, Any]], None] | None = None,
    reconcile_path: Path = Path("tb140_history_reconcile.jsonl"),
) -> dict[str, int]:
    """INSERT 保持 DO NOTHING；仅在持久化对账成功后条件替换 tdx_local。

    默认对账写当前运行目录 tb140_history_reconcile.jsonl；可显式指定路径或持久化 sink。

    对账失败回滚；结果记录在本函数拥有的事务结束后写入。缺少事务接口时拒绝替换。
    不建连接、不加载应用或数据库依赖，允许注入假连接。
    BJ 未经 confirm_bj_offline_volume_units 确认时不进入写入参数，返回
    blocked_bj_unconfirmed 计数；混合批次中的沪深行仍按原规则处理。
    """
    writable_rows = [row for row in rows if not _bj_write_unconfirmed(row)]
    blocked_bj = len(rows) - len(writable_rows)
    material = [row_insert_params(row, licence_id) for row in writable_rows]
    outcomes: list[dict[str, Any]] = []
    sink = reconcile_sink or jsonl_reconcile_sink(reconcile_path)
    # 不能把外层事务中的 savepoint 释放误记成 committed。
    status = getattr(getattr(conn, "info", None), "transaction_status", 0)
    if status is not None and int(status) != 0:
        raise RowReject("connection_transaction_already_active")
    tx = getattr(conn, "transaction", None)
    transactional = callable(tx) or callable(getattr(conn, "commit", None))

    def count() -> int:
        with conn.cursor() as cur:
            cur.execute(COUNT_DAILY_BARS_SQL)
            fetched = cur.fetchone()
            return int(fetched[0]) if fetched is not None else 0

    def run() -> dict[str, int]:
        before = count()
        replaced = 0
        if material:
            with conn.cursor() as cur:
                cur.executemany(INSERT_DAILY_BARS_SQL, material)
                if transactional:
                    for row, params in zip(writable_rows, material):
                        cur.execute(SELECT_EXISTING_BAR_SQL, params[:3])
                        fetchall = getattr(cur, "fetchall", None)
                        if callable(fetchall):
                            candidates = fetchall()
                        else:
                            fetched = cur.fetchone()
                            candidates = [fetched] if fetched is not None else []
                        candidates = [dict(item) if isinstance(item, Mapping) else
                                      dict(zip(("row_count", "source", "open", "high", "low", "close", "pre_close", "volume", "amount", "is_suspended"), item))
                                      for item in candidates]
                        old = next((item for item in candidates
                                    if item.get("source") == "tdx_local"
                                    and all(str(item.get(key, row[key])) == str(row[key])
                                            for key in ("code", "trade_date", "adj_type"))), None)
                        if old is None:
                            continue
                        replacement_id = str(uuid.uuid4())
                        outcome = {"kind": "replace_result", "replacement_id": replacement_id,
                                   "code": row["code"], "trade_date": str(row["trade_date"]),
                                   "adj_type": row["adj_type"], "existing_source": "tdx_local",
                                   "incoming_source": SOURCE, "value": "rolled_back"}
                        for record in _replacement_records(old, row, replacement_id):
                            sink(record)
                            if outcome not in outcomes:
                                outcomes.append(outcome)
                        cur.execute(REPLACE_TDX_LOCAL_SQL, params[3:] + params[:3])
                        changed = max(0, int(cur.rowcount))
                        replaced += changed
                        outcome["value"] = "committed" if changed else "skipped"
        after = count()
        result = {"count_before": before, "count_after": after, "inserted": after - before}
        if blocked_bj:
            result["blocked_bj_unconfirmed"] = blocked_bj
        if replaced or reconcile_sink is not None:
            result["replaced"] = replaced
        return result

    def finish(rolled_back: bool = False) -> None:
        for outcome in outcomes:
            value = "rolled_back" if rolled_back else outcome["value"]
            sink(dict(outcome, value=value, replace_result=value))

    try:
        if callable(tx):
            with tx():
                result = run()
        elif transactional:
            try:
                result = run()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        else:
            result = run()
    except BaseException as exc:
        try:
            finish(rolled_back=True)
        except BaseException:
            exc.add_note("replace_result_write_failed")
        raise
    finish()
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

    SQL 和此入口的非替换路径均保留 DO NOTHING；替换使用相同的对账、条件更新和回执。
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
