"""R-R3：用冻结的沪深公开公告离线核对仓库交易日历。

原始公告、URL、抓取时刻及SHA256在仓库外sources.json；本脚本不联网。
普通周末是交易日枚举基准，公告点名的调休周末另行校验，不当作开市日。
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import re
from datetime import date, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
YEARS = tuple(range(2020, 2027))
EXCHANGES = ("sse", "szse")
HOLIDAYS = ("元旦", "春节", "清明节", "劳动节", "端午节", "中秋节", "国庆节")
EXPECTED_PARAGRAPHS = {2020: 6, 2021: 7, 2022: 7, 2023: 6, 2024: 7, 2025: 6, 2026: 7}
SOURCE_IDS = {
    *(f"{exchange}_annual_{year}" for exchange in EXCHANGES for year in YEARS),
    "sse_2020_extension",
    "szse_2020_extension",
}
DIFF_FIELDS = [
    "category",
    "year",
    "date_or_range",
    "sse_open",
    "szse_open",
    "repository_open",
    "source_ids",
    "note",
]
DATE_TEXT = r"(\d{1,2})月(\d{1,2})日"
WEEKDAY_TEXT = r"(?:（[^）]*）)?"
RANGE_RE = re.compile(
    DATE_TEXT + WEEKDAY_TEXT + r"\s*至\s*" + DATE_TEXT + WEEKDAY_TEXT + "休市"
)
SINGLE_RE = re.compile(DATE_TEXT + WEEKDAY_TEXT + "休市")
REOPEN_RE = re.compile(DATE_TEXT + WEEKDAY_TEXT + r"(?:起)?(?:照常|正常)开市")
WEEKEND_CLAUSE_RE = re.compile(r"另外[，,]([^。]*为周末休市)")
ANY_DATE_RE = re.compile(DATE_TEXT)
EXTENSION_RE = re.compile(r"延长2020年春节休市至(\d{1,2})月(\d{1,2})日")


def require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def dates_between(start: date, end: date) -> list[date]:
    require(start <= end, f"negative date range: {start}..{end}")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


class ArticleText(HTMLParser):
    """仅提取公告正文容器，避免导航和脚本中的日期混入。"""

    def __init__(self, exchange: str) -> None:
        super().__init__(convert_charrefs=True)
        self.exchange = exchange
        self.depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        matched = (
            self.exchange == "sse"
            and tag == "div"
            and "allZoom" in (attributes.get("class") or "").split()
        ) or (
            self.exchange == "szse"
            and tag == "div"
            and attributes.get("id") == "desContent"
        )
        if self.depth and tag == "div":
            self.depth += 1
        elif matched:
            self.depth = 1
        if self.depth and tag in {"p", "br", "div", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self.depth and tag in {"p", "div", "tr"}:
            self.parts.append("\n")
        if self.depth and tag == "div":
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth:
            self.parts.append(data)


def article_lines(raw: bytes, exchange: str) -> list[str]:
    require(exchange in EXCHANGES, f"unknown exchange: {exchange}")
    parser = ArticleText(exchange)
    parser.feed(raw.decode("utf-8-sig"))
    require(parser.parts, f"article body not found: {exchange}")
    return [
        normalized
        for part in "".join(parser.parts).splitlines()
        if (normalized := re.sub(r"\s+", " ", part).strip())
    ]


def text_date(year: int, match: re.Match[str], offset: int = 0) -> date:
    month, day = (int(match.group(index + offset)) for index in (1, 2))
    return date(year, month, day)


def parse_annual(raw: bytes, exchange: str, year: int) -> dict:
    lines = article_lines(raw, exchange)
    holiday_lines = [
        line
        for line in lines
        if "休市" in line and any(name in line for name in HOLIDAYS)
    ]
    require(
        len(holiday_lines) == EXPECTED_PARAGRAPHS[year],
        f"{exchange} {year} holiday paragraphs: {len(holiday_lines)}",
    )
    closed: set[date] = set()
    reopens: set[date] = set()
    weekend_noted: set[date] = set()
    closed_by_holiday: dict[str, set[date]] = {}
    reopen_by_holiday: dict[str, set[date]] = {}
    for line in holiday_lines:
        label = "/".join(name for name in HOLIDAYS if name in line)
        line_closed: set[date] = set()
        ranges = list(RANGE_RE.finditer(line))
        for match in ranges:
            start = text_date(year, match)
            end = text_date(year, match, offset=2)
            line_closed.update(dates_between(start, end))
        for match in SINGLE_RE.finditer(line):
            if any(
                container.start() <= match.start() and match.end() <= container.end()
                for container in ranges
            ):
                continue
            line_closed.add(text_date(year, match))
        require(line_closed, f"unparsed holiday closure: {exchange} {year} {label}")
        line_reopens = {text_date(year, match) for match in REOPEN_RE.finditer(line)}
        require(line_reopens, f"missing reopen: {exchange} {year} {label}")
        require(not line_closed & line_reopens, f"closed/reopen overlap: {label}")
        for clause in WEEKEND_CLAUSE_RE.findall(line):
            noted = {text_date(year, match) for match in ANY_DATE_RE.finditer(clause)}
            require(noted and all(day.weekday() >= 5 for day in noted), clause)
            weekend_noted.update(noted)
        closed.update(line_closed)
        reopens.update(line_reopens)
        closed_by_holiday[label] = line_closed
        reopen_by_holiday[label] = line_reopens
    require(not weekend_noted & reopens, f"weekend/reopen overlap: {exchange} {year}")
    return {
        "closed": closed,
        "reopens": reopens,
        "weekend_noted": weekend_noted,
        "closed_by_holiday": closed_by_holiday,
        "reopen_by_holiday": reopen_by_holiday,
        "paragraphs": len(holiday_lines),
    }


def apply_2020_extension(annual: dict, raw: bytes, exchange: str) -> dict:
    adjusted = copy.deepcopy(annual)
    text = " ".join(article_lines(raw, exchange))
    matches = list(EXTENSION_RE.finditer(text))
    require(len(matches) == 1, f"2020 extension end not unique: {exchange}")
    end = text_date(2020, matches[0])
    reopens = {text_date(2020, match) for match in REOPEN_RE.finditer(text)}
    require(reopens == {date(2020, 2, 3)}, f"2020 extension reopen: {exchange}")
    labels = [label for label in adjusted["closed_by_holiday"] if "春节" in label]
    require(len(labels) == 1, f"2020 spring label: {exchange}")
    label = labels[0]
    original = adjusted["closed_by_holiday"][label]
    original_end = max(original)
    require(end > original_end, f"extension does not extend: {exchange}")
    added = set(dates_between(original_end + timedelta(days=1), end))
    adjusted["closed"].update(added)
    adjusted["closed_by_holiday"][label].update(added)
    adjusted["reopens"].difference_update(adjusted["reopen_by_holiday"][label])
    adjusted["reopens"].update(reopens)
    adjusted["reopen_by_holiday"][label] = reopens
    adjusted["extension"] = {
        "original_end": original_end.isoformat(),
        "adjusted_end": end.isoformat(),
        "added_closed_days": [day.isoformat() for day in sorted(added)],
        "reopen": "2020-02-03",
    }
    return adjusted


def load_manifest(raw_dir: Path) -> dict[str, dict]:
    entries = json.loads((raw_dir / "sources.json").read_text(encoding="utf-8"))
    require(isinstance(entries, list), "sources.json must be a list")
    result = {}
    for entry in entries:
        source_id = entry["id"]
        require(source_id in SOURCE_IDS, f"unexpected source: {source_id}")
        require(source_id not in result, f"duplicate source: {source_id}")
        require(entry.get("raw_file") == f"{source_id}.html", source_id)
        parsed = urlsplit(entry["url"])
        require(parsed.scheme == "https", source_id)
        require(parsed.hostname in {"www.sse.com.cn", "www.szse.cn"}, source_id)
        raw = (raw_dir / entry["raw_file"]).read_bytes()
        require(len(raw) == entry["bytes"], f"byte count: {source_id}")
        require(sha256(raw) == entry["sha256"], f"sha256: {source_id}")
        result[source_id] = entry
    require(
        set(result) == SOURCE_IDS,
        f"source coverage: {sorted(SOURCE_IDS - set(result))}",
    )
    return result


def compress_ranges(days: list[date]) -> list[str]:
    if not days:
        return []
    ranges = []
    start = previous = days[0]
    for current in days[1:]:
        if (current - previous).days != 1:
            ranges.append(f"{start}..{previous}")
            start = current
        previous = current
    ranges.append(f"{start}..{previous}")
    return ranges


def compare_year(
    year: int,
    sse: dict,
    szse: dict,
    coverage_start: date,
    coverage_end: date,
    repository_open: set[date],
    source_ids: list[str],
) -> tuple[list[dict], list[dict], dict]:
    differences: list[dict] = []
    daily: list[dict] = []
    uncovered = []
    mismatch = conflict = 0
    all_days = dates_between(date(year, 1, 1), date(year, 12, 31))
    for current in all_days:
        sse_open = current.weekday() < 5 and current not in sse["closed"]
        szse_open = current.weekday() < 5 and current not in szse["closed"]
        covered = coverage_start <= current <= coverage_end
        repo_open = current in repository_open if covered else None
        if not covered:
            uncovered.append(current)
        category = ""
        if sse_open != szse_open:
            category = "exchange_source_conflict"
            conflict += 1
        elif covered and repo_open != sse_open:
            category = (
                "repository_extra_open" if repo_open else "repository_missing_open"
            )
            mismatch += 1
        if category:
            differences.append(
                {
                    "category": category,
                    "year": year,
                    "date_or_range": current.isoformat(),
                    "sse_open": sse_open,
                    "szse_open": szse_open,
                    "repository_open": repo_open,
                    "source_ids": ";".join(source_ids),
                    "note": "两所冲突，未代为裁定"
                    if conflict and not category.startswith("repository")
                    else "逐日开市状态不同",
                }
            )
        daily.append(
            {
                "date": current.isoformat(),
                "sse_open": sse_open,
                "szse_open": szse_open,
                "repository_open": repo_open,
                "comparison": category
                or ("covered_match" if covered else "coverage_missing"),
            }
        )
    for interval in compress_ranges(uncovered):
        differences.append(
            {
                "category": "repository_coverage_missing",
                "year": year,
                "date_or_range": interval,
                "sse_open": "",
                "szse_open": "",
                "repository_open": "",
                "source_ids": ";".join(source_ids),
                "note": "仓库无覆盖；不判定逐日一致或不一致",
            }
        )
    stats = {
        "year": year,
        "calendar_days": len(all_days),
        "sse_open_days": sum(row["sse_open"] for row in daily),
        "szse_open_days": sum(row["szse_open"] for row in daily),
        "holiday_closed_days": len(sse["closed"]),
        "holiday_weekday_closed_days": sum(day.weekday() < 5 for day in sse["closed"]),
        "weekend_noted_days": len(sse["weekend_noted"]),
        "repository_covered_days": len(all_days) - len(uncovered),
        "repository_uncovered_days": len(uncovered),
        "repository_mismatch_days": mismatch,
        "exchange_source_conflict_days": conflict,
        "source_ids": source_ids,
    }
    if "extension" in sse:
        stats["adjustment"] = sse["extension"]
    return differences, daily, stats


def csv_bytes(rows: list[dict], fields: list[str]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def audit(raw_dir: Path, calendar_path: Path) -> dict[str, bytes | dict]:
    manifest = load_manifest(raw_dir)
    calendar = json.loads(calendar_path.read_text(encoding="utf-8"))
    coverage_start = date.fromisoformat(calendar["coverage_start"])
    coverage_end = date.fromisoformat(calendar["coverage_end"])
    open_values = calendar["open_days"]
    require(
        open_values == sorted(set(open_values)),
        "repository open_days not sorted/unique",
    )
    repository_open = {date.fromisoformat(value) for value in open_values}
    require(
        all(coverage_start <= day <= coverage_end for day in repository_open),
        "repository open_days outside declared coverage",
    )
    all_differences: list[dict] = []
    all_daily: list[dict] = []
    year_stats = []
    for year in YEARS:
        parsed = {}
        source_ids = []
        for exchange in EXCHANGES:
            annual_id = f"{exchange}_annual_{year}"
            parsed[exchange] = parse_annual(
                (raw_dir / f"{annual_id}.html").read_bytes(), exchange, year
            )
            source_ids.append(annual_id)
            if year == 2020:
                extension_id = f"{exchange}_2020_extension"
                parsed[exchange] = apply_2020_extension(
                    parsed[exchange],
                    (raw_dir / f"{extension_id}.html").read_bytes(),
                    exchange,
                )
                source_ids.append(extension_id)
        differences, daily, stats = compare_year(
            year,
            parsed["sse"],
            parsed["szse"],
            coverage_start,
            coverage_end,
            repository_open,
            source_ids,
        )
        all_differences.extend(differences)
        all_daily.extend(daily)
        year_stats.append(stats)
    daily_fields = ["date", "sse_open", "szse_open", "repository_open", "comparison"]
    daily_raw = csv_bytes(all_daily, daily_fields)
    summary = {
        "task": "R-R3",
        "range": {
            "start": "2020-01-01",
            "end": "2026-12-31",
            "calendar_days": len(all_daily),
        },
        "repository": {
            "coverage_start": coverage_start.isoformat(),
            "coverage_end": coverage_end.isoformat(),
            "open_days": len(repository_open),
        },
        "totals": {
            "repository_coverage_gap_rows": sum(
                row["category"] == "repository_coverage_missing"
                for row in all_differences
            ),
            "repository_mismatch_days": sum(
                row["category"].startswith("repository_")
                and row["category"] != "repository_coverage_missing"
                for row in all_differences
            ),
            "exchange_source_conflict_days": sum(
                row["category"] == "exchange_source_conflict" for row in all_differences
            ),
        },
        "daily_comparison_sha256": sha256(daily_raw),
        "years": year_stats,
        "sources": [
            {
                key: manifest[source_id][key]
                for key in ("id", "url", "fetched_at_utc", "bytes", "sha256")
            }
            for source_id in sorted(manifest)
        ],
    }
    return {
        "differences.csv": csv_bytes(all_differences, DIFF_FIELDS),
        "summary.json": (
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        ).encode("utf-8"),
        "daily_comparison.csv": daily_raw,
        "summary": summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument(
        "--calendar", type=Path, default=ROOT / "config/trading_calendar.json"
    )
    parser.add_argument("--output-dir", type=Path, default=HERE)
    parser.add_argument("--daily-output", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = audit(args.raw_dir, args.calendar)
    if args.check:
        for name in ("differences.csv", "summary.json"):
            require(
                (HERE / name).read_bytes() == result[name],
                f"stale generated file: {name}",
            )
    else:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name in ("differences.csv", "summary.json"):
            (args.output_dir / name).write_bytes(result[name])
    if args.daily_output:
        args.daily_output.write_bytes(result["daily_comparison.csv"])
    print(json.dumps(result["summary"]["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
