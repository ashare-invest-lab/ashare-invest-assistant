#!/usr/bin/env python3
"""T-B140c 离线装载：把已校验的日线历史行变成幂等 INSERT，不连真实库、不读证书、不出网。

口径出处：
- 接口字段 t/o/h/l/c/v/a/pc/sf：T003-mairui-capability.md §2（日线字段）。
- v 单位为手、a 为元、n 为不复权：T003 GAP2 / T-B05-recheck.md「日线 v 同样是手」/ T-A136「v(手)」。
- 库内 volume 为股：daily-bars-tdx 契约「两侧均为股」，故 volume = v × 100。
- 主键 (code, trade_date, adj_type)，ON CONFLICT DO NOTHING：app/db/tables/market.py。
- active 证书判定对齐 owned_daily_read._licence（status=active、未删除、未暂停、未过期、无 hold）。
"""
from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

HIST_ST = date(2023, 11, 13)
HIST_ET = date(2026, 11, 13)
ADJ_TYPE = "none"
SOURCE = "mairui"
VOL_MULT = 100  # 手 → 股

# 公开交易所代码段 + 本批 codes_ashare.txt 实际前缀。
# 不用 startswith("6"/"9") 这种宽泛规则（既有 tb140_daily_bars.mkt 会把 920 判成 SH）。
_SH = ("600", "601", "603", "605", "688", "689")
_SZ = ("000", "001", "002", "003", "300", "301", "302")
_BJ = ("430", "431", "432", "433", "434", "435", "436", "437", "438", "439",
       "830", "831", "832", "833", "834", "835", "836", "837", "838", "839",
       "870", "871", "872", "873", "874", "875", "876", "877", "878", "879",
       "920")
_CODE_RE = re.compile(r"^[0-9]{6}$")
_QUALIFIED_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


class RowReject(ValueError):
    """单行校验失败，不含任何密钥。"""


class CodeReject(ValueError):
    """代码身份无法认定，不含任何密钥。"""


def market_of(code: str) -> str:
    """只接受已知 3 位前缀；未知代码直接拒绝，不回落到 SZ/SH。"""
    raw = str(code).strip()
    if not _CODE_RE.fullmatch(raw):
        raise CodeReject("code_not_six_digits")
    if raw.startswith(_SH):
        return "SH"
    if raw.startswith(_SZ):
        return "SZ"
    if raw.startswith(_BJ):
        return "BJ"
    raise CodeReject("code_prefix_unknown")


def qualified_code(code: str) -> str:
    return f"{code.strip()}.{market_of(code)}"


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


def _trade_date(value: Any) -> date:
    text = str(value).strip()
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
            return date.fromisoformat(text)
        if re.fullmatch(r"[0-9]{8}", text):
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError as exc:
        raise RowReject("trade_date_invalid") from exc
    raise RowReject("trade_date_invalid")


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


def validate_bar(row: Any, expected_code: str, *, st: date = HIST_ST, et: date = HIST_ET) -> dict[str, Any] | None:
    """通过则返回可入库行；日期越界返回 None（跳过、不伪造）；其余抛 RowReject。"""
    if not _QUALIFIED_RE.fullmatch(expected_code):
        raise CodeReject("qualified_code_invalid")
    if not isinstance(row, dict):
        raise RowReject("row_not_object")
    _identity_ok(row, expected_code)
    day = _trade_date(row.get("t"))
    if day < st or day > et:
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
    st: date = HIST_ST,
    et: date = HIST_ET,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """只接受 list body。返回 (rows, rejects)。不编造缺日。"""
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
    """生成可独立执行的幂等 INSERT。licence_id 必须是已裁定值，不在此查库。"""
    material = list(rows)
    lookup = ACTIVE_LICENCE_SQL.replace("\n", "\n-- ")
    lines = [
        "-- T-B140c offline-generated; ON CONFLICT DO NOTHING; no destructive DML or DDL",
        f"-- bind_note={bind_note}",
        "\\set ON_ERROR_STOP on",
        "BEGIN;",
        f"-- active licence lookup (apply-time, for operator check):\n-- {lookup}",
    ]
    if not material:
        lines.extend(["-- no rows", "COMMIT;"])
        return "\n".join(lines) + "\n"
    cols = (
        "code,trade_date,adj_type,open,high,low,close,pre_close,"
        "volume,amount,is_suspended,source,source_licence_id"
    )
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
    return "\n".join(lines) + "\n"


def apply_insert_offline(
    existing: set[tuple[str, str, str]],
    rows: Sequence[dict[str, Any]],
) -> dict[str, int]:
    """内存模拟 ON CONFLICT DO NOTHING，不连库。"""
    table = set(existing)
    inserted = 0
    skipped = 0
    for row in rows:
        if row.get("source") != SOURCE or row.get("adj_type") != ADJ_TYPE:
            raise RowReject("source_or_adj_forged")
        key = (str(row["code"]), str(row["trade_date"]), ADJ_TYPE)
        if key in table:
            skipped += 1
            continue
        table.add(key)
        inserted += 1
    return {"inserted": inserted, "skipped_existing": skipped, "total": len(table)}


def write_normalized(path: Path, code: str, rows: Sequence[dict[str, Any]], rejects: Sequence[dict[str, str]]) -> None:
    payload = {
        "code": qualified_code(code),
        "window": {"st": HIST_ST.isoformat(), "et": HIST_ET.isoformat()},
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


def apply_daily_bars(
    conn: Any,
    rows: Sequence[dict[str, Any]],
    licence_id: str | None = None,
) -> dict[str, int]:
    """单事务幂等写入 daily_bars。只执行参数化 INSERT … ON CONFLICT DO NOTHING 与 SELECT count。

    禁止 DELETE / TRUNCATE / DDL / UPDATE。返回写前、写后计数与新插入行数。
    连接对象需提供 cursor()，以及可选的 transaction() 或 commit/rollback（psycopg 3.x 或同等假对象）。
    """
    material = [row_insert_params(row, licence_id) for row in rows]

    def _count(owner: Any) -> int:
        with owner.cursor() as cur:
            cur.execute(COUNT_DAILY_BARS_SQL)
            fetched = cur.fetchone()
            return int(fetched[0]) if fetched is not None else 0

    def _run(owner: Any) -> dict[str, int]:
        before = _count(owner)
        if material:
            with owner.cursor() as cur:
                cur.executemany(INSERT_DAILY_BARS_SQL, material)
        after = _count(owner)
        return {"count_before": before, "count_after": after, "inserted": after - before}

    tx = getattr(conn, "transaction", None)
    if callable(tx):
        with tx():
            return _run(conn)
    if hasattr(conn, "commit"):
        try:
            result = _run(conn)
            conn.commit()
            return result
        except BaseException:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                rollback()
            raise
    return _run(conn)
