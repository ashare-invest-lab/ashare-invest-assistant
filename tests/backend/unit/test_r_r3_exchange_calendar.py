"""R-R3：合成公开公告的离线解析与逐日比较；不读取真实归档或网络。"""

from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "docs/strategies/R-R3/audit_exchange_calendar.py"
SPEC = importlib.util.spec_from_file_location("r_r3_exchange_calendar", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ANNUAL_LINES = [
    "（一）元旦：1月1日（星期三）休市，1月2日（星期四）起照常开市。",
    "（二）春节：1月24日（星期五）至1月30日（星期四）休市，1月31日（星期五）起照常开市。另外，1月19日（星期日）、2月1日（星期六）为周末休市。",
    "（三）清明节：4月4日（星期六）至4月6日（星期一）休市，4月7日（星期二）起照常开市。",
    "（四）劳动节：5月1日（星期五）至5月5日（星期二）休市，5月6日（星期三）起照常开市。另外，4月26日（星期日）、5月9日（星期六）为周末休市。",
    "（五）端午节：6月25日（星期四）至6月27日（星期六）休市，6月29日（星期一）起照常开市。另外，6月28日（星期日）为周末休市。",
    "（六）国庆节、中秋节：10月1日（星期四）至10月8日（星期四）休市，10月9日（星期五）起照常开市。另外，9月27日（星期日）、10月10日（星期六）为周末休市。",
]
EXTENSION = (
    "根据批准，延长2020年春节休市至2月2日（星期日），2月3日（星期一）起照常开市。"
)


def notice(exchange: str, lines: list[str]) -> bytes:
    container = (
        '<div class="allZoom">' if exchange == "sse" else '<div id="desContent">'
    )
    return (
        container + "".join(f"<p><span>{line}</span></p>" for line in lines) + "</div>"
    ).encode()


def adjusted_pair() -> tuple[dict, dict]:
    result = []
    for exchange in ("sse", "szse"):
        annual = MODULE.parse_annual(notice(exchange, ANNUAL_LINES), exchange, 2020)
        result.append(
            MODULE.apply_2020_extension(annual, notice(exchange, [EXTENSION]), exchange)
        )
    return result[0], result[1]


def test_public_notice_wrappers_and_weekend_noted_are_equivalent() -> None:
    sse = MODULE.parse_annual(notice("sse", ANNUAL_LINES), "sse", 2020)
    szse = MODULE.parse_annual(notice("szse", ANNUAL_LINES), "szse", 2020)
    assert sse["closed"] == szse["closed"]
    assert sse["reopens"] == szse["reopens"]
    assert date(2020, 1, 30) in sse["closed"]
    assert date(2020, 1, 31) not in sse["closed"]
    assert sse["weekend_noted"] == szse["weekend_noted"]
    assert all(day.weekday() >= 5 for day in sse["weekend_noted"])


def test_2020_extension_overrides_original_spring_reopen() -> None:
    for exchange in ("sse", "szse"):
        annual = MODULE.parse_annual(notice(exchange, ANNUAL_LINES), exchange, 2020)
        adjusted = MODULE.apply_2020_extension(
            annual, notice(exchange, [EXTENSION]), exchange
        )
        assert {date(2020, 1, 31), date(2020, 2, 1), date(2020, 2, 2)} <= adjusted[
            "closed"
        ]
        assert date(2020, 2, 3) in adjusted["reopens"]
        assert date(2020, 1, 31) not in adjusted["reopens"]
        assert date(2020, 1, 31) not in annual["closed"], "不得改写原公告解析结果"


def test_daily_comparison_separates_date_mismatch_and_coverage() -> None:
    sse, szse = adjusted_pair()
    official_open = {
        day
        for day in MODULE.dates_between(date(2020, 1, 1), date(2020, 12, 31))
        if day.weekday() < 5 and day not in sse["closed"]
    }
    repository_open = official_open - {date(2020, 2, 3)} | {date(2020, 1, 31)}
    differences, daily, stats = MODULE.compare_year(
        2020,
        sse,
        szse,
        date(2020, 1, 1),
        date(2020, 12, 31),
        repository_open,
        ["synthetic"],
    )
    assert len(daily) == 366
    assert {(row["category"], row["date_or_range"]) for row in differences} == {
        ("repository_extra_open", "2020-01-31"),
        ("repository_missing_open", "2020-02-03"),
    }
    assert stats["repository_mismatch_days"] == 2
    _, uncovered_daily, uncovered_stats = MODULE.compare_year(
        2020, sse, szse, date(2026, 1, 1), date(2026, 12, 31), set(), ["synthetic"]
    )
    assert uncovered_stats["repository_mismatch_days"] == 0
    assert uncovered_stats["repository_uncovered_days"] == 366
    assert all(row["comparison"] == "coverage_missing" for row in uncovered_daily)


def test_exchange_conflict_is_not_voted_into_repository_difference() -> None:
    sse = {"closed": {date(2026, 1, 5)}, "weekend_noted": set()}
    szse = {"closed": set(), "weekend_noted": set()}
    repository_open = {
        day
        for day in MODULE.dates_between(date(2026, 1, 1), date(2026, 12, 31))
        if day.weekday() < 5 and day not in sse["closed"]
    }
    differences, daily, stats = MODULE.compare_year(
        2026,
        sse,
        szse,
        date(2026, 1, 1),
        date(2026, 12, 31),
        repository_open,
        ["synthetic"],
    )
    conflict = [
        row for row in differences if row["category"] == "exchange_source_conflict"
    ]
    assert [row["date_or_range"] for row in conflict] == ["2026-01-05"]
    assert stats["exchange_source_conflict_days"] == 1
    assert stats["repository_mismatch_days"] == 0
    assert (
        next(row for row in daily if row["date"] == "2026-01-05")["repository_open"]
        is False
    )


def test_manifest_rejects_tampered_public_bytes(tmp_path: Path) -> None:
    entries = []
    for source_id in sorted(MODULE.SOURCE_IDS):
        raw = b"<html>synthetic</html>"
        (tmp_path / f"{source_id}.html").write_bytes(raw)
        entries.append(
            {
                "id": source_id,
                "url": "https://www.sse.com.cn/synthetic",
                "raw_file": f"{source_id}.html",
                "bytes": len(raw),
                "sha256": "0" * 64
                if source_id == "sse_annual_2020"
                else MODULE.sha256(raw),
            }
        )
    (tmp_path / "sources.json").write_text(json.dumps(entries), encoding="utf-8")
    with pytest.raises(ValueError, match="sha256: sse_annual_2020"):
        MODULE.load_manifest(tmp_path)
