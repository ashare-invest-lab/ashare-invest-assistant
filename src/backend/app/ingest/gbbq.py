"""权息快照离线解码；映射遵循契约 §2.5、§3.4，不访问网络或数据库。"""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from zipfile import ZipFile


class GbbqRefused(Exception):  # noqa: N818 - 契约用语「拒绝」
    """快照整包拒绝，不返回部分事件。"""


@dataclass(frozen=True)
class GbbqEvent:
    """每股口径的除权除息事件；六位小数为契约约定（未验证）。"""

    code: str
    ex_date: date
    cash_per_share: Decimal
    rights_price: Decimal
    bonus_ratio: Decimal
    rights_ratio: Decimal
    source: str = "tdx_gbbq"


def decode_gbbq(content: bytes, keys: Sequence[int]) -> list[GbbqEvent]:
    """逐块照搬 DS load_gbbq 的三轮解码；截断、非法日期、重复事件整包拒绝。"""
    if len(content) < 4:
        raise GbbqRefused("truncated_file")
    (count,) = struct.unpack_from("<I", content)
    if len(content) < 4 + count * 29:
        raise GbbqRefused("truncated_file")
    if len(keys) != 1042:
        raise GbbqRefused("invalid_keys")
    result: list[GbbqEvent] = []
    seen: set[tuple[str, date]] = set()
    offset = 4
    mask = 0xFFFFFFFF
    for _ in range(count):
        clear = bytearray()
        for _ in range(3):
            left, right = struct.unpack_from("<II", content, offset)
            left ^= keys[0x44 // 4]
            for j in range(16, 0, -1):
                f = (
                    keys[0x448 // 4 + ((left >> 16) & 255)] + keys[0x48 // 4 + (left >> 24)]
                ) & mask
                f ^= keys[0x848 // 4 + ((left >> 8) & 255)]
                f = (f + keys[0xC48 // 4 + (left & 255)]) & mask
                left, right = (right ^ f ^ keys[j]) & mask, left
            clear.extend(struct.pack("<II", right ^ keys[0], left))
            offset += 8
        clear.extend(content[offset : offset + 5])
        offset += 5
        market, raw_code, exdate, category, cash, pp, bonus, rights = struct.unpack(
            "<B7sIBffff", clear
        )
        if category != 1 or market not in (0, 1):
            continue
        try:
            symbol = raw_code.rstrip(b"\0").decode("gbk")
            ex_date = date(exdate // 10000, exdate // 100 % 100, exdate % 100)
        except UnicodeDecodeError as exc:
            raise GbbqRefused("invalid_code") from exc
        except ValueError as exc:
            raise GbbqRefused("invalid_date") from exc
        if len(symbol) != 6 or not symbol.isascii() or not symbol.isdigit():
            raise GbbqRefused("invalid_code")
        code = symbol + (".SH" if market == 1 else ".SZ")
        if (code, ex_date) in seen:
            raise GbbqRefused("duplicate_event")
        seen.add((code, ex_date))
        values: list[Decimal] = []
        for raw, divisor in ((cash, 10), (pp, 1), (bonus, 10), (rights, 10)):
            try:
                value = (Decimal(str(raw)) / divisor).quantize(
                    Decimal("0.000001"), rounding=ROUND_HALF_UP
                )
            except InvalidOperation as exc:
                raise GbbqRefused("out_of_range") from exc
            if not value.is_finite():
                raise GbbqRefused("non_finite")
            if value.adjusted() + 1 > 14:  # 契约 Numeric(20,6) 的整数位限制。
                raise GbbqRefused("out_of_range")
            values.append(value)
        result.append(GbbqEvent(code, ex_date, values[0], values[1], values[2], values[3]))
    return result


def load_pytdx_keys() -> tuple[int, ...]:
    """运行时借用格式表，不在项目依赖或仓库中保存真实密钥表。"""
    try:
        from pytdx.reader.gbbq_reader import GbbqReader  # type: ignore[import-not-found]
    except ImportError as exc:
        raise GbbqRefused("pytdx_unavailable") from exc
    raw = bytes.fromhex(GbbqReader.hexdump_keys)
    return struct.unpack("<" + "I" * (len(raw) // 4), raw)


def read_gbbq_zip(
    path: Path, expected_sha256: str, keys: Sequence[int]
) -> tuple[str, list[GbbqEvent]]:
    """先校验完整 zip 的 SHA256，再读取 gbbq 成员；不接受部分结果。"""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
        actual = digest.hexdigest()
        if actual != expected_sha256:
            raise GbbqRefused("sha256_mismatch")
        stream.seek(0)
        with ZipFile(stream) as archive:
            try:
                content = archive.read("gbbq")
            except KeyError as exc:
                raise GbbqRefused("missing_gbbq") from exc
    return actual, decode_gbbq(content, keys)


def ref_price(
    pc_raw: Decimal, cash: Decimal, rights_price: Decimal, bonus: Decimal, rights: Decimal
) -> Decimal:
    """契约 §2.5 的单次除权参考价；调用方负责选择前收和适用事件。"""
    return (pc_raw - cash + rights_price * rights) / (1 + bonus + rights)
