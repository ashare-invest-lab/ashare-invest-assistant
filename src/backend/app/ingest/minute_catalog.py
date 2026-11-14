"""离线分钟文件目录的纯计算；不读取行情数值，不向 PG 写分钟线。"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class CatalogEntry:
    """契约 §3.3 的目录列（未验证）；登记时间由数据库生成。"""

    source: str
    code: str
    kind: str
    date_from: date
    date_to: date
    rel_path: str
    sha256: str
    row_count: int
    splice_segment: str
    generator: str


def validate_rel_path(rel: str) -> str:
    """存储前统一正斜杠，拒绝绝对路径、盘符、空段和上级目录段。"""
    normalized = rel.replace("\\", "/")
    if (
        normalized.startswith("/")
        or ":" in normalized
        or any(part in ("", "..") for part in normalized.split("/"))
    ):
        raise ValueError("不安全的相对路径")
    return normalized


def resolve(root: str, rel: str) -> Path:
    """按根目录的路径语法拼接；Windows 路径应在对应部署机上打开。"""
    relative = validate_rel_path(rel)
    base = PureWindowsPath(root) if PureWindowsPath(root).drive else PurePosixPath(root)
    return Path(str(base / relative))


def hf_entries_from_manifest(
    rows: Iterable[Mapping[str, str]], generator: str
) -> tuple[list[CatalogEntry], Counter[str]]:
    """直接登记 2022plus 产物；含退市沪深股，排除 BJ 与 HF 分段之后的文件。"""
    prefixes = {
        "SH": {"600", "601", "603", "605", "688", "689"},
        "SZ": {"000", "001", "002", "003", "300", "301", "302"},
    }
    entries: list[CatalogEntry] = []
    counts: Counter[str] = Counter()
    for row in rows:
        exchange, symbol = row["exchange"], row["symbol"]
        if exchange == "BJ" or row["is_bj"].lower() == "true":
            counts["skip_bj"] += 1
            continue
        nrows = int(row["rows"])
        if nrows == 0:
            counts["skip_empty"] += 1
            continue
        if not re.fullmatch(r"[0-9]{6}", symbol) or symbol[:3] not in prefixes.get(exchange, set()):
            counts["reject_prefix"] += 1
            continue
        try:
            stamps = [datetime.fromisoformat(row[key]) for key in ("first_ts", "last_ts")]
            if any(stamp.utcoffset() is None for stamp in stamps):
                raise ValueError("清单时间必须带时区")
            first, last = [stamp.astimezone(ZoneInfo("Asia/Shanghai")).date() for stamp in stamps]
        except ValueError:
            counts["reject_date"] += 1
            continue
        if last > date(2026, 8, 6):  # 契约 §3.2 的 HF 分段上界。
            counts["reject_after_hf_end"] += 1
            continue
        if nrows < 0 or first > last or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            counts["reject_catalog"] += 1
            continue
        entries.append(
            CatalogEntry(
                source="hf_1min",
                code=f"{symbol}.{exchange}",
                kind="1m",
                date_from=first,
                date_to=last,
                rel_path=validate_rel_path(f"hf-1min/2022plus/{exchange}/{symbol}.parquet"),
                sha256=row["sha256"],
                row_count=nrows,
                splice_segment="hf",
                generator=generator,
            )
        )
        counts["registered"] += 1
    return entries, counts
