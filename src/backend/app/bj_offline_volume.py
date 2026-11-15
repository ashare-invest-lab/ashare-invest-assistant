"""BJ 离线量单位确认与进程内写入门闩；仅依赖标准库。

CLI 与离线装载脚本共用此处的判定、异常类型及确认状态。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

VOL_MULT = 100  # 手 → 股
_bj_offline_volume_codes: frozenset[str] = frozenset()

# 公开交易所代码段 + 本批 codes_ashare.txt 实际前缀。
# 不用 startswith("6"/"9") 这种宽泛规则（既有 tb140_daily_bars.mkt 会把 920 判成 SH）。
_SH = ("600", "601", "603", "605", "688", "689")
_SZ = ("000", "001", "002", "003", "300", "301", "302")
_BJ = (
    "430",
    "431",
    "432",
    "433",
    "434",
    "435",
    "436",
    "437",
    "438",
    "439",
    "830",
    "831",
    "832",
    "833",
    "834",
    "835",
    "836",
    "837",
    "838",
    "839",
    "870",
    "871",
    "872",
    "873",
    "874",
    "875",
    "876",
    "877",
    "878",
    "879",
    "920",
)
_CODE_RE = re.compile(r"^[0-9]{6}$")
_QUALIFIED_RE = re.compile(r"^[0-9]{6}\.(SH|SZ|BJ)$")


class RowReject(ValueError):  # noqa: N818 - 保留离线装载的公开异常名。
    """单行校验失败，不含任何密钥。"""


class CodeReject(ValueError):  # noqa: N818 - 保留离线装载的公开异常名。
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
    if isinstance(value, bool) or value is None:
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
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
            return date.fromisoformat(text)
        if re.fullmatch(r"[0-9]{8}", text):
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError as exc:
        raise RowReject("trade_date_invalid") from exc
    raise RowReject("trade_date_invalid")


def confirm_bj_offline_volume_units(
    pairs: Iterable[Mapping[str, Mapping[str, Any]]],
) -> frozenset[str]:
    """用调用方提供的本地对照确认 BJ 量单位；纯计算，不读取文件、出网或连库。

    每项为 {"mairui": 原始行, "tdx_local": 本地行}：原始行须含 code/t/v，
    本地行须含 code/trade_date/volume/source。代码须为同一合法 .BJ 标准码，
    日期须相同，source 须为 tdx_local，且原始 v（手）×100 精确等于 volume（股）。
    不自动转码；全部对照一致且至少涵盖 20 只不同代码才通过，返回确认代码集。

    模块在进程内默认未确认；成功后允许各写入口写 BJ（不限于样本代码）。
    每次调用先撤销旧确认，失败抛 RowReject，不能跨调用累加样本或沿用旧确认。
    确认不从产物恢复；新进程调用 Python 写入入口仍须先离线确认。
    """
    global _bj_offline_volume_codes
    _bj_offline_volume_codes = frozenset()
    matched: set[str] = set()
    for pair in pairs:
        if not isinstance(pair, Mapping):
            raise RowReject("bj_offline_pair_invalid")
        mairui, tdx = pair.get("mairui"), pair.get("tdx_local")
        if not isinstance(mairui, Mapping) or not isinstance(tdx, Mapping):
            raise RowReject("bj_offline_pair_invalid")
        code = tdx.get("code")
        if (
            not isinstance(code, str)
            or not _QUALIFIED_RE.fullmatch(code)
            or not code.endswith(".BJ")
            or mairui.get("code") != code
        ):
            raise RowReject("bj_offline_code_mismatch")
        try:
            if qualified_code(code[:6]) != code:
                raise RowReject("bj_offline_code_mismatch")
        except CodeReject:
            raise RowReject("bj_offline_code_mismatch") from None
        if tdx.get("source") != "tdx_local":
            raise RowReject("bj_offline_source_invalid")
        if _trade_date(mairui.get("t")) != _trade_date(tdx.get("trade_date")):
            raise RowReject("bj_offline_date_mismatch")
        lots = _decimal(mairui.get("v"), "v")
        shares = _decimal(tdx.get("volume"), "volume")
        if (
            lots < 0
            or shares < 0
            or shares != shares.to_integral_value()
            or lots * VOL_MULT != shares
        ):
            raise RowReject("bj_offline_volume_mismatch")
        matched.add(code)
    if len(matched) < 20:
        raise RowReject("bj_offline_requires_20_distinct_codes")
    _bj_offline_volume_codes = frozenset(matched)
    return _bj_offline_volume_codes


def _bj_write_unconfirmed(row: Mapping[str, Any]) -> bool:
    return not _bj_offline_volume_codes and str(row.get("code", "")).endswith(".BJ")
