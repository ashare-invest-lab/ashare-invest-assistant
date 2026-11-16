"""BJ 离线量确认与身份、日期校验；只依赖标准库，不读取外部凭据。"""
from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation

_BJ_ISOLATED_CONFIRMATIONS: frozenset[str] = frozenset()
_bj_offline_volume_codes: frozenset[str] = frozenset()
_bj_confirmation_pid: int | None = None

# 公开交易所代码段 + 本批 codes_ashare.txt 实际前缀。
_SH = ("600", "601", "603", "605", "688", "689")
_SZ = ("000", "001", "002", "003", "300", "301", "302")
_BJ = ("430", "431", "432", "433", "434", "435", "436", "437", "438", "439",
       "830", "831", "832", "833", "834", "835", "836", "837", "838", "839",
       "870", "871", "872", "873", "874", "875", "876", "877", "878", "879",
       "920")
_CODE_RE = re.compile(r"^[0-9]{6}$")
_QUALIFIED_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


class RowReject(ValueError):  # noqa: N818 - preserve the probe API
    """单行校验失败，不含任何密钥。"""


class CodeReject(ValueError):  # noqa: N818 - preserve the probe API
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


def _decimal(value: object, name: str) -> Decimal:
    if isinstance(value, (bool, float)) or value is None:
        raise RowReject(f"field_invalid:{name}")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise RowReject(f"field_invalid:{name}") from exc
    if not number.is_finite():
        raise RowReject(f"field_invalid:{name}")
    return number


def _trade_date(value: object) -> date:
    text = str(value).strip()
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2} 00:00:00", text):
        text = text[:10]
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
            return date.fromisoformat(text)
        if re.fullmatch(r"[0-9]{8}", text):
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError as exc:
        raise RowReject("trade_date_invalid") from exc
    raise RowReject("trade_date_invalid")


def confirm_bj_offline_volume_units(
    pairs: Iterable[Mapping[str, Mapping[str, object]]],
) -> frozenset[str]:
    """用调用方提供的本地对照确认 BJ 量单位；纯计算，不读取文件、出网或连库。

    同一共同交易日至少 20 个合法 BJ 码，两侧均非停牌且量为正，手×100 精确等于股。
    每次先撤销旧确认；返回匹配码仅表示对算通过，不构成生产许可。
    只有显式注入的隔离测试清单与匹配码的交集可写；生产清单恒为空。
    """
    global _bj_offline_volume_codes, _bj_confirmation_pid
    _bj_offline_volume_codes = frozenset()
    _bj_confirmation_pid = None
    by_day: dict[date, set[str]] = {}
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise RowReject("bj_offline_pair_invalid")
        mairui, tdx = pair.get("mairui"), pair.get("tdx_local")
        if not isinstance(mairui, Mapping) or not isinstance(tdx, Mapping):
            raise RowReject("bj_offline_pair_invalid")
        code = tdx.get("code")
        if (not isinstance(code, str) or not _QUALIFIED_RE.fullmatch(code)
                or not code.endswith(".BJ") or mairui.get("code") != code):
            raise RowReject("bj_offline_code_mismatch")
        try:
            if qualified_code(code[:6]) != code:
                raise RowReject("bj_offline_code_mismatch")
        except CodeReject:
            raise RowReject("bj_offline_code_mismatch") from None
        if tdx.get("source") != "tdx_local":
            raise RowReject("bj_offline_source_invalid")
        day = _trade_date(mairui.get("t"))
        if day != _trade_date(tdx.get("trade_date")):
            raise RowReject("bj_offline_date_mismatch")
        lots = _decimal(mairui.get("v"), "v")
        shares = _decimal(tdx.get("volume"), "volume")
        if lots < 0 or shares < 0:
            raise RowReject("bj_offline_volume_mismatch")
        if (lots == 0 or shares == 0 or _is_suspended(mairui.get("sf"))
                or _is_suspended(tdx.get("is_suspended"))):
            continue
        sign, digits, exponent = lots.as_tuple()
        assert isinstance(exponent, int)  # finite Decimal, checked above  # noqa: S101
        exact_shares = Decimal((sign, digits, exponent + 2))
        if shares != shares.to_integral_value() or exact_shares != shares:
            raise RowReject("bj_offline_volume_mismatch")
        by_day.setdefault(day, set()).add(code)
    matched = max(by_day.values(), key=len, default=set())
    if len(matched) < 20:
        raise RowReject("bj_offline_requires_20_distinct_codes")
    _bj_confirmation_pid = os.getpid()
    _bj_offline_volume_codes = frozenset(matched) & _BJ_ISOLATED_CONFIRMATIONS
    return frozenset(matched)


def _bj_write_unconfirmed(row: Mapping[str, object]) -> bool:
    return (
        _bj_confirmation_pid != os.getpid()
        or row.get("code") not in _BJ_ISOLATED_CONFIRMATIONS
        or row.get("code") not in _bj_offline_volume_codes
    ) and str(row.get("code", "")).endswith(".BJ")


def _is_suspended(value: object) -> bool:
    return value in (1, "1", True, "true", "True")
