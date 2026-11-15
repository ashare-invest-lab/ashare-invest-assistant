"""日线压缩包离线遍历；单位自检保持 T-B133 的整文件判定。"""

from __future__ import annotations

import re
from collections.abc import Iterator, Set
from dataclasses import dataclass
from datetime import date
from zipfile import ZipFile

from app.ingest.tdx_local import DAY_LAYOUT, ParseResult, parse_day_bytes, unit_suspect


@dataclass(frozen=True)
class DayRefusal:
    """跳过原因或文件拒绝；文件拒绝使运行状态为 partial，其他文件继续。"""

    reason: str
    file_refused: bool = False


def iter_day_zip(
    zf: ZipFile, eligible: Set[str], before: date | None
) -> Iterator[tuple[str, ParseResult | DayRefusal]]:
    """仅解析目录与前缀一致且在证券资格集中的日线；跳过也返回原因供调用方计数。"""
    seen_members: set[str] = set()
    for member in zf.infolist():
        name = member.filename.replace("\\", "/").lower()
        if member.is_dir() or not name.endswith(".day"):
            yield "", DayRefusal("not_target_file")
            continue
        match = re.fullmatch(r"(sh|sz|bj)/lday/(sh|sz|bj)([0-9]{6})\.day", name)
        if match is None or match[1] != match[2]:
            yield "", DayRefusal("name_invalid")
            continue
        code = f"{match[3]}.{match[1].upper()}"
        if code not in eligible:
            yield code, DayRefusal("not_eligible")
            continue
        if name in seen_members:
            yield code, DayRefusal("duplicate_member", file_refused=True)
            continue
        seen_members.add(name)
        data = zf.read(member)
        if len(data) % DAY_LAYOUT.size:
            yield code, DayRefusal("truncated_file", file_refused=True)
            continue
        # 连被记录级拒绝的有效日期也检查，不能因坏价格而漏掉同日重复。
        seen_dates: set[date] = set()
        duplicate = False
        for raw_day, *_ in DAY_LAYOUT.iter_unpack(data):
            try:
                day = date(raw_day // 10000, raw_day // 100 % 100, raw_day % 100)
            except ValueError:
                continue
            if day in seen_dates:
                duplicate = True
                break
            seen_dates.add(day)
        if duplicate:
            yield code, DayRefusal("duplicate_date", file_refused=True)
            continue
        parsed = parse_day_bytes(code, data)
        if unit_suspect(parsed.bars):
            yield code, DayRefusal("unit_suspect", file_refused=True)
            continue
        # 本单避开正在运行的麦蕊回填窗口的可选过滤，并非契约截止日 D。
        if before is not None:
            kept = [bar for bar in parsed.bars if bar.trade_date < before]
            parsed.rejected["filtered_before"] += len(parsed.bars) - len(kept)
            parsed.bars = kept
        yield code, parsed
