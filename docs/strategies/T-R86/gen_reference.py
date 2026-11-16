#!/usr/bin/env python3
"""Frozen formal gaps and independent proxies; no network or production imports."""
import argparse
import csv
import hashlib
import io
import json
import math
import re
import struct
import subprocess
import types
import zipfile
from bisect import bisect_right
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLES = (
    "sh600519", "sz000001", "sh600228", "sh600825", "sh600293",
    "sh603159", "sh603307", "sz001225", "sh688610", "sz300502",
    "sz300750", "sh688981", "sh688801", "sz001246", "sz001381",
    "sz301569", "sz301718", "bj920000", "bj920085", "sz000972",
)
DATES = ("2026-06-30", "2026-09-30", "2026-11-09")
FEATURES = {
    "F09": ("profit_cagr_3y", "pct", (3, 4, 5)),
    "F10": ("dividend_continuous_years", "years", (6, 7, 8, 9)),
    "F11": ("limit_up_count_20d", "count", ()),
    "F12": ("fin_report_count", "count", (1, 2)),
}
SOURCE_SHA = "860b8b3693c40c24f666c3c81dc9c7de245f300178ce004db6900664353376da"
FIELDS = ("code,market,as_of,feature,input_key,value,unit,status,fq_basis,"
          "null_reason,available_at,st_history_status,source_ids,source_url,"
          "jzrq,plrq,access_date,rules_sha256,proxy_value,proxy_flags").split(",")
BAR = struct.Struct("<IIIIIfII")
TR81 = "f70789f2fd52d4654e3a45b442608e25ee43fda1"
PROXY_SHA = "f4e8d1a62d87cb5aebb8be64038a8920262e7875feabc2d24590668c2321031a"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect_archives(day_path, gbbq_path, sources):
    # Structural audit only: neither snapshot proves historical availability.
    for path, kind in ((day_path, "day_zip"), (gbbq_path, "gbbq_zip")):
        expected = next(r["sha256"] for r in sources if r["kind"] == kind)
        require(sha256(path) == expected, f"{kind}: source hash mismatch")
    with zipfile.ZipFile(day_path) as archive:
        members = {n.replace("\\", "/"): n for n in archive.namelist()}
        for stem in (*SAMPLES, "sh000001"):
            raw = archive.read(members[f"{stem[:2]}/lday/{stem}.day"])
            require(raw and len(raw) % 32 == 0, f"{stem}: truncated day")
            rows = list(BAR.iter_unpack(raw))
            days = [r[0] for r in rows]
            require(days == sorted(set(days)), f"{stem}: duplicate/unordered dates")
            for row in rows:
                n = row[0]
                date(n // 10000, n // 100 % 100, n % 100)
                require(math.isfinite(row[5]), f"{stem}: nonfinite amount")
    with zipfile.ZipFile(gbbq_path) as archive:
        require(archive.testzip() is None, "gbbq CRC mismatch")
        require("gbbq" in archive.namelist(), "missing gbbq member")
    # No sf/pc in this day schema. No decoded, PIT-proven ex-rights reference.


def inspect_rules(path):
    text = path.read_text(encoding="utf-8")
    segments = re.findall(
        r'- effective_from: "([\d-]+)"(.*?)(?=\n  - effective_from:|\Z)',
        text, re.S)
    require(bool(segments), "missing market rule segments")
    for start, block in segments:
        date.fromisoformat(start)
        part = block.split("price_limit_pct:", 1)[1].split("no_limit:", 1)[0]
        rates = dict(re.findall(r"^      (\w+): (\d+)", part, re.M))
        require(set(rates) == {"main_board", "main_board_st", "chinext", "star", "bse"},
                "unknown market rule layout")
        require(all(0 < int(v) < 100 for v in rates.values()), "invalid rates")
    return sha256(path)


def visible(row, as_of):
    # Access date and a historical NOTICE_DATE are not first_seen_at evidence.
    if row["available_at"] == "null" or row["first_seen_at"] == "null":
        return False
    times = [datetime.fromisoformat(row[k]) for k in ("available_at", "first_seen_at")]
    require(all(t.tzinfo is not None for t in times), "timezone missing")
    return max(times) <= datetime.fromisoformat(as_of)


def reference_rows(sources, rules_hash):
    result = []
    for stem in SAMPLES:
        code = stem[2:]
        for d in DATES:
            for fid, (key, unit, questions) in FEATURES.items():
                kind = "dividend" if fid == "F10" else "income"
                evidence = [r for r in sources if r["code"] == code and r["kind"] == kind]
                if fid == "F09":
                    evidence = [r for r in evidence if r["jzrq"].endswith("12-31")]
                if fid == "F11":
                    evidence = [r for r in sources if r["kind"] in ("day_zip", "gbbq_zip")]
                    # Later ST discoveries stay in the audit ledger, never backfilled.
                as_of = d + "T15:05:00+08:00"
                cutoff = as_of if fid == "F11" else d + "T15:00:00+08:00"
                require(evidence, f"missing source ledger: {code}/{fid}")
                require(not any(visible(r, cutoff) for r in evidence),
                        "new visible evidence: review method before regenerating frozen nulls")
                gaps = ["historical_visibility_unverified"]
                gaps += {
                    "F09": ["comparability_unverified", "listing_age_unverified"],
                    "F10": ["payment_completion_unverified", "year_closure_unverified",
                            "break_year_unverified"],
                    "F11": ["exchange_calendar_missing", "sf_missing", "pc_exdiv_reference_missing",
                            "unlimited_days_unverified", "st_history_unverified", "threshold_unapproved"],
                    "F12": ["full_history_scope_unverified", "listing_identity_unverified"],
                }[fid]
                if all(r["jzrq"] == "null" for r in evidence) and fid != "F11":
                    gaps.append("source_empty_not_zero")
                if stem.startswith("bj"):
                    gaps.append("HG2_bse_excluded")
                def joined(field):
                    return ";".join(dict.fromkeys(r[field] for r in evidence))
                result.append(dict(zip(FIELDS, (
                    code, stem[:2].upper(), as_of, fid, "f." + key, "null", unit,
                    "待 T-A197 裁定", ";".join(f"F-Q{q:02}:Opt-A" for q in questions)
                    or "not_applicable:F11/F37/market_rules", ";".join(gaps), "null",
                    "未验证" if fid == "F11" else "not_applicable", joined("source_id"),
                    joined("source_url"), joined("jzrq"), joined("plrq"), "2026-11-15",
                    rules_hash if fid == "F11" else "not_applicable"))))
    return result


def render(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def load_tr81():
    def frozen(name):
        return subprocess.check_output(
            ["git", "show", f"{TR81}:docs/strategies/T-R81/{name}"], cwd=HERE)
    module = types.ModuleType("tr81_frozen")
    module.__file__ = str(HERE / "gen_reference.py")
    exec(compile(frozen("gen_reference.py"), "tr81_frozen", "exec"), module.__dict__)
    baseline = {(r["code"], r["d"]): r for r in
                csv.DictReader(io.StringIO(frozen("reference_values.csv").decode()))
                if r["input_key"] == "f.limit_up_count_20d"}
    return module, baseline


def financial_reports(data, calendar, d, listing):
    visible_reports, flags = {}, {"deadline_notice_proxy", "restated_value_risk",
                                 "listing_first_bar_proxy", "scope_snapshot_unverified"}
    for period, notice, profit in data["income"]["rows"]:
        period, notice = period[:10], notice[:10] if notice else ""
        if period > d or not notice or notice > d or notice <= period or period < listing:
            continue
        year, suffix = int(period[:4]), period[5:]
        require(suffix in ("03-31", "06-30", "09-30", "12-31"), "unknown period")
        deadline = (f"{year + 1}-04-30" if suffix == "12-31" else
                    f"{year}-" + {"03-31": "04-30", "06-30": "08-31", "09-30": "10-31"}[suffix])
        # On-time: min(next(deadline), next(notice)); late: never backdate to deadline.
        anchor = min(deadline, notice) if notice <= deadline else notice
        pos = bisect_right(calendar, anchor)
        if pos == len(calendar) or calendar[pos] > d:
            continue
        available = calendar[pos] + "T09:30:00+08:00"
        if notice > deadline:
            flags.add("late_or_restated")
        candidate = (notice, available, profit)
        if period in visible_reports:
            require(visible_reports[period] == candidate, f"conflicting period: {period}")
        visible_reports[period] = candidate
    return visible_reports, flags


def finance_proxy(fid, data, calendar, d, listing):
    reports, flags = financial_reports(data, calendar, d, listing if fid == "F12" else "0001-01-01")
    gap, value = None, None
    if listing > d:
        gap = "before_first_bar_proxy"
    elif fid == "F12":
        flags.add("distinct_jzrq")
        value = str(len(reports)) if reports else None
        gap = None if reports else "no_visible_reports_not_proven_empty"
    elif fid == "F09":
        flags.update(("annual_endpoints", "comparability_unverified"))
        annual = sorted(p for p in reports if p.endswith("12-31"))
        if not annual:
            gap = "missing_endpoint"
        else:
            end = annual[-1]
            base = f"{int(end[:4]) - 3}-12-31"
            endpoints = [reports.get(p, (None, None, None))[2] for p in (base, end)]
            if int(d.replace("-", "")) < int(listing.replace("-", "")) + 30000:
                gap = "listing_under_three_years_proxy"
            elif any(v is None for v in endpoints):
                gap = "missing_endpoint"
            else:
                b, e = map(lambda v: Decimal(str(v)), endpoints)
                require(b.is_finite() and e.is_finite(), "nonfinite profit")
                gap = "base_nonpositive" if b <= 0 else "end_negative" if e < 0 else "end_zero" if e == 0 else None
                if not gap:
                    value = format(((e / b) ** (Decimal(1) / 3) * 100 - 100)
                                   .quantize(Decimal(".01"), rounding=ROUND_HALF_UP), "f")
                    flags.add(f"endpoints={base}|{end}")
    else:
        flags.update(("ex_date_proxy", "fiscal_year", "cash_only_no_buybacks"))
        # A dated implementation is necessary, but cannot prove annual closure
        # or turn an absent year into an explicit zero (F-Q07 Run definition).
        events = []
        for period, notice, ex_date, status, cash in data["dividend"]["rows"]:
            if not notice or notice[:10] > d or period[:10] > d:
                continue
            if status == "实施分配" and ex_date and ex_date[:10] < d and cash is not None:
                require(Decimal(str(cash)).is_finite(), "nonfinite cash")
                if Decimal(str(cash)) > 0:
                    events.append(period[:4])
        flags.add("observed_cash_years=" + "|".join(sorted(set(events))))
        gap = ("source_empty_not_zero" if not data["dividend"]["rows"] else
               "year_closure_and_break_unverified" if events else "no_visible_implemented_cash")
    return value or "null", sorted(flags | ({"gap=" + gap} if gap else set()))


def add_proxies(rows, args):
    tr81, baseline = load_tr81()
    require(sha256(args.rules) == sha256(HERE.parents[2] / "config/market_rules.yaml"),
            "T-R81 rule file differs")
    path = HERE / "sources/proxy_inputs.jsonl"
    require(sha256(path) == PROXY_SHA, "proxy input hash mismatch")
    inputs = {r["code"]: r for r in map(json.loads, path.read_text().splitlines())}
    with zipfile.ZipFile(args.day_zip) as archive:
        members = {n.replace("\\", "/"): n for n in archive.namelist()}
        bars = {s: list(BAR.iter_unpack(archive.read(members[f"{s[:2]}/lday/{s}.day"])))
                for s in (*SAMPLES, "sh000001")}
    calendar = [r[0] for r in bars["sh000001"]]
    dates = list(map(tr81.iso, calendar))
    segments = tr81.rules()
    contexts = {s: tr81.proxy_context(bars[s], calendar, tr81.board_of(s), segments) for s in SAMPLES}
    for row in rows:
        stem, d = row["market"].lower() + row["code"], row["as_of"][:10]
        flags = ["proxy_only", "T_R86_applicability_pending", "T_A197_pending",
                 "calendar_proxy=sh000001_bars"]
        if row["feature"] == "F11":
            proxy = list(tr81.proxies(bars[stem], calendar, int(d.replace("-", "")),
                         tr81.board_of(stem), contexts[stem], stem in tr81.ST_CURRENT_SNAPSHOT_HITS))[6]
            value = proxy["proxy_value"]
            expected = baseline[(row["code"], d)]["proxy_value"]
            require(value == expected, f"F11 != T-R81 B7: {stem}/{d}: {value} != {expected}")
            flags += [proxy["proxy_flags"], "window=" + proxy["proxy_window_start"] + "|" + d,
                      "valid_bars=" + str(proxy["proxy_valid_bars"])]
            flags += ["gap=" + g for g in proxy["proxy_gap"].split(";")]
            if stem in tr81.ST_CURRENT_SNAPSHOT_HITS:
                flags.append("current_snapshot_exclusion_lookahead")
        else:
            value, extra = finance_proxy(row["feature"], inputs[row["code"]], dates, d,
                                         tr81.iso(bars[stem][0][0]))
            flags += extra
            if stem.startswith("bj"):
                value = "null"
                flags.append("gap=HG2")
        row.update(proxy_value=value, proxy_flags=";".join(flags))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day-zip", required=True, type=Path)
    parser.add_argument("--gbbq-zip", required=True, type=Path)
    parser.add_argument("--rules", required=True, type=Path)
    parser.add_argument("--sources", type=Path, default=HERE / "sources/public_sources.csv")
    parser.add_argument("--output", type=Path, default=HERE / "reference_values.csv")
    parser.add_argument("--features", nargs="+", choices=FEATURES, default=list(FEATURES))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    require(sha256(args.sources) == SOURCE_SHA, "source ledger hash mismatch")
    with args.sources.open(encoding="utf-8", newline="") as stream:
        sources = list(csv.DictReader(stream))
    inspect_archives(args.day_zip, args.gbbq_zip, sources)
    rows = reference_rows(sources, inspect_rules(args.rules))
    add_proxies(rows, args)
    if set(args.features) != set(FEATURES):
        with args.output.open(encoding="utf-8", newline="") as stream:
            old = list(csv.DictReader(stream))
        identity = lambda r: (r["code"], r["as_of"], r["feature"])
        require([identity(r) for r in old] == [identity(r) for r in rows], "row identities changed")
        rows = [new if new["feature"] in args.features else prev for prev, new in zip(old, rows)]
    output = render(rows)
    if args.check:
        require(args.output.read_bytes() == output, "reference CSV differs")
    else:
        args.output.write_bytes(output)
    print(f"OK: {len(rows)} rows; formal values frozen; proxies reproduced and F11 == T-R81 B7")


if __name__ == "__main__":
    main()
