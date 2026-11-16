#!/usr/bin/env python3
"""T-R81 draft: strict null references, A01–A03 proxies and raw diagnostics."""
import argparse
import csv
import hashlib
import io
import math
import re
import struct
import tempfile
import zipfile
from collections import Counter
from bisect import bisect_left, bisect_right
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from statistics import stdev

# Fixed before stock selection; never select dates from returns or CLI input.
DATES = (20260630, 20260930, 20261109)
SAMPLES = (
    "sh600519", "sz000001", "sh600228", "sh600825", "sh600293",
    "sh603159", "sh603307", "sz001225", "sh688610", "sz300502",
    "sz300750", "sh688981", "sh688801", "sz001246", "sz001381",
    "sz301569", "sz301718", "bj920000", "bj920085", "sz000972",
)
HASHES = (
    "b6c2a5043a76d8f9b9752b3cca1952ed697ac7bd5eebe88cd7a96809f47cee46",
    "c1cbc818d748079aa79749393729dbcf378adf258a22734762d19b885ed0eeab",
)
FEATURES = (
    ("list_days", "trading_days", 0), ("amount_20d_avg", "CNY", 0),
    ("volatility_20d", "ratio", 6), ("intraday_amplitude_20d", "ratio", 6),
    ("ma_trend", "pct", 2), ("momentum_60d", "pct", 2),
    ("limit_up_count_20d", "count", 0), ("turnover_20d_avg", "pct", 4),
)
FIELDS = (
    "code,market,board,d,input_key,value,unit,precision,null_reason_or_gap,"
    "window_start,window_end,valid_bars,list_date_source,data_sha256_short,"
    "first_bar_date,diag_start,diag_end,diag_observed_bars,diag_missing_dates,"
    "diag_amount_sum,diag_amount_mean,diag_limit_matches,diag_one_price_matches,"
    "proxy_value,proxy_gap,proxy_window_start,proxy_window_end,proxy_valid_bars,"
    "calendar_proxy,proxy_flags"
).split(",")
HERE = Path(__file__).resolve().parent
BAR = struct.Struct("<5If2I")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def iso(n):
    return date(n // 10000, n // 100 % 100, n % 100).isoformat()


def half_up(value, places=0):
    return format(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")


def verify(path, expected):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    require(h.hexdigest() == expected, "source_sha256_mismatch")


def read_bars(archive, stem, scratch):
    member = f"{stem[:2]}\\lday\\{stem}.day"
    raw = archive.read(member)
    target = scratch / f"{stem}.day"
    target.write_bytes(raw)  # Only selected members, always in temporary storage.
    require(len(raw) % BAR.size == 0, "truncated_day")
    rows = list(BAR.iter_unpack(target.read_bytes()))
    require(bool(rows), "empty_day")
    dates = [r[0] for r in rows]
    require(dates == sorted(set(dates)), "unordered_or_duplicate_dates")
    for r in rows:
        iso(r[0])
        require(math.isfinite(r[5]), "nonfinite_amount")
    return rows


def board_of(stem):
    if stem.startswith("bj"):
        return "bse"
    if stem[2:].startswith("688"):
        return "star"
    if stem[2:].startswith(("300", "301")):
        return "chinext"
    return "main_board"


def rules():
    # Read only the needed integer price-limit section; fail on layout changes.
    text = (HERE.parents[2] / "config/market_rules.yaml").read_text()
    segments = []
    for start, block in re.findall(r'- effective_from: "([\d-]+)"(.*?)(?=\n  - effective_from:|\Z)', text, re.S):
        section = block.split("price_limit_pct:", 1)[1].split("no_limit:", 1)[0]
        rates = dict((k, int(v)) for k, v in re.findall(r'^      (\w+): (\d+)', section, re.M))
        require(set(rates) == {"main_board", "main_board_st", "chinext", "star", "bse"}, "rule_keys")
        for key in ("registered_ipo_first_days", "bse_ipo_first_days"):
            rates[key] = int(re.search(rf"^      {key}: (\d+)", block, re.M)[1])
        segments.append((start, rates))
    require(bool(segments), "missing_rule_segments")
    return sorted(segments)


def proxy_context(rows, calendar, board, segments):
    valid = [r for r in rows if r[6] > 0 and 0 < r[3] <= min(r[1], r[4])
             <= max(r[1], r[4]) <= r[2]]
    previous = {cur[0]: prev for prev, cur in zip(valid, valid[1:])}
    limits, unlimited, suspected = {}, set(), set()
    listing = bisect_left(calendar, rows[0][0])
    for cur in valid:
        eligible = [rates for start, rates in segments if start <= iso(cur[0])]
        if not eligible:
            continue  # Historical rules before the first segment are not invented.
        rates = eligible[-1]
        age = bisect_right(calendar, cur[0]) - listing
        days = rates["bse_ipo_first_days" if board == "bse" else "registered_ipo_first_days"]
        if iso(rows[0][0]) >= segments[0][0] and age <= days:
            unlimited.add(cur[0])
            continue
        if cur[0] in previous:
            prev = previous[cur[0]][4]
            rate = rates[board]  # Main-board ST unknown: A03 uses non-ST 10%.
            limits[cur[0]] = max(prev + 1, int(half_up(Decimal(prev) * (1 + Decimal(rate) / 100))))
            if abs(cur[1] - prev) * 100 > prev * rate:
                suspected.add(cur[0])
    return valid, previous, limits, unlimited, suspected


def proxies(rows, calendar, d, board, context):
    valid, previous, limits, unlimited, suspected = context
    history = calendar[:bisect_right(calendar, d)]
    w20, w60, span = history[-20:], history[-60:], history[-61:]
    observed = [r for r in valid if r[0] <= d]
    short = [r for r in observed if r[0] in w20]
    long = [r for r in observed if r[0] in w60]
    base = [r for r in observed if r[0] <= span[0]]
    end = observed[-1] if observed else None
    for index, (_, _, precision) in enumerate(FEATURES):
        window = span if index == 5 else w60 if index == 4 else w20
        chosen = [r for r in observed if r[0] in window]
        flags = ["threshold_unapproved", "raw_price", "suspension_proxy=missing_bar",
                 "ipo_no_limit_proxy", "exdiv_heuristic_unverified"]
        gaps, value = [], None
        if index == 1:
            flags.append("amount_unit_unverified")
            chosen = [r for r in chosen if r[5] >= 0]
        if index in (2, 3, 6):
            chosen = [r for r in chosen if r[0] not in unlimited]
            if index == 6:
                if board == "main_board":
                    flags.append("st_unverified")
                if any(r[0] not in limits for r in chosen):
                    gaps.append("limit_price_unavailable")
            else:
                chosen = [r for r in chosen if r[0] in previous]
        start, stop = window[0], d
        if index == 0:
            start = rows[0][0]
            chosen = [t for t in history if t >= start]
            value = Decimal(len(chosen))
        if index == 5 and base and end:
            start, stop = base[-1][0], end[0]
        if index in (2, 3, 6) and chosen:
            start = min([start] + [previous[r[0]][0] for r in chosen if r[0] in previous])
        if board == "bse":
            gaps.append("HG2")
        if rows[0][0] > d:
            gaps.append("before_first_bar_proxy")
        if index == 7:
            gaps.append("float_shares_unavailable")
        if index and any(r[0] == d and r not in valid for r in rows):
            gaps.append("invalid_evaluation_bar")
        if index and (len(chosen) < (45 if index in (4, 5) else 15)
                      or (index == 4 and len(short) < 15)):
            gaps.append("insufficient_window")
        if index == 5 and (len(span) < 61 or not base or not end):
            gaps.append("momentum_anchor_unavailable")
        # B1 counts listing sessions, not a price window. B8 has no float shares.
        events = sorted(t for t in suspected if start <= t <= stop) if 0 < index < 7 else []
        if events:
            gaps.append("excluded_exdiv_suspected")
            flags.append("exdiv_suspected_dates=" + "|".join(map(iso, events)))
        if not gaps:
            if index == 1:
                value = sum((Decimal.from_float(r[5]) for r in chosen), Decimal(0)) / len(chosen)
            elif index in (2, 3):
                ratios = [Decimal(r[4] - previous[r[0]][4] if index == 2 else r[2] - r[3])
                          / previous[r[0]][4] for r in chosen]
                value = (Decimal.from_float(stdev(map(float, ratios))) if index == 2
                         else sum(ratios) / len(ratios))
            elif index == 4:
                value = (Decimal(sum(r[4] for r in short)) / len(short)
                         / (Decimal(sum(r[4] for r in long)) / len(long)) - 1) * 100
            elif index == 5:
                value = (Decimal(end[4]) / base[-1][4] - 1) * 100
            elif index == 6:
                value = Decimal(sum(r[4] == limits[r[0]] for r in chosen))
        yield dict(proxy_value="null" if gaps else half_up(value, precision),
                   proxy_gap=";".join(gaps) or "none", proxy_window_start=iso(start),
                   proxy_window_end=iso(stop), proxy_valid_bars=len(chosen),
                   calendar_proxy="sh000001_bars", proxy_flags=";".join(flags))


def diagnostics(rows, reference_dates, d, board, segments):
    # This is an observed-index-date slice, NEVER the authoritative W20 calendar.
    observed = [t for t in reference_dates if t <= d][-20:]
    chosen = [r for r in rows if r[0] in observed]
    present = {r[0] for r in chosen}
    missing = [iso(t) for t in observed if rows[0][0] <= t and t not in present]
    amounts = [Decimal.from_float(r[5]) for r in chosen if r[5] >= 0]
    total = sum(amounts, Decimal(0))
    matches, one_price = [], []
    for prev, cur in zip(rows, rows[1:]):
        if cur[0] not in observed or prev[4] <= 0:
            continue
        eligible = [rates for start, rates in segments if start <= iso(cur[0])]
        if not eligible:
            continue
        rates = eligible[-1]
        alternatives = {rates[board]}
        if board == "main_board":
            alternatives.add(rates["main_board_st"])
        for rate in sorted(alternatives):
            upper = max(prev[4] + 1, int(half_up(Decimal(prev[4]) * (1 + Decimal(rate) / 100))))
            if cur[4] == upper:
                evidence = f"{iso(cur[0])}@{rate}%"
                matches.append(evidence)
                if cur[1] == cur[2] == cur[3] == cur[4]:
                    one_price.append(evidence)
    return dict(diag_start=iso(observed[0]), diag_end=iso(observed[-1]),
                diag_observed_bars=len(chosen), diag_missing_dates=";".join(missing) or "none_observed",
                diag_amount_sum=str(total) if amounts else "null",
                diag_amount_mean=half_up(total / len(amounts)) if amounts else "null",
                diag_limit_matches=";".join(matches) or "none_observed",
                diag_one_price_matches=";".join(one_price) or "none_observed")


def generate(day_zip, gbbq_zip):
    verify(day_zip, HASHES[0])
    verify(gbbq_zip, HASHES[1])
    segments = rules()
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, FIELDS, lineterminator="\n")
    writer.writeheader()
    with tempfile.TemporaryDirectory(prefix="tr81-", dir="/tmp") as temp:
        scratch = Path(temp)
        with zipfile.ZipFile(gbbq_zip) as archive:
            raw = archive.read("gbbq")
            (scratch / "gbbq").write_bytes(raw)
            count, = struct.unpack_from("<I", raw)
            require(len(raw) == 4 + 29 * count, "gbbq_container_length")
            # Encoded records have no authorized field decoder or PIT evidence.
        with zipfile.ZipFile(day_zip) as archive:
            ref = [r[0] for r in read_bars(archive, "sh000001", scratch)]
            require(set(DATES) <= set(ref), "evaluation_date_without_index_bar")
            for stem in SAMPLES:
                rows = read_bars(archive, stem, scratch)
                board = board_of(stem)
                context = proxy_context(rows, ref, board, segments)
                for d in DATES:
                    diag = diagnostics(rows, ref, d, board, segments)
                    proxy_rows = list(proxies(rows, ref, d, board, context))
                    for index, (key, unit, precision) in enumerate(FEATURES):
                        gaps = ["calendar_missing", "pit_finality_missing", "spec_ambiguous:A01"]
                        if index:
                            gaps += ["sf_missing"]
                        if 0 < index < 7:
                            gaps += ["spec_ambiguous:A02"]
                        if index == 1:
                            gaps += ["amount_unit_unverified"]
                        if index in (2, 3, 4, 5):
                            gaps += ["factor_missing", "spec_ambiguous:A03"]
                        if index == 6:
                            gaps += ["pre_close_missing", "historical_st_and_no_limit_missing", "exrights_unverified"]
                        if index == 7:
                            gaps += ["vendor_factor_missing:Q02", "float_shares_unverified"]
                        if board == "bse":
                            gaps += ["bse_excluded:HG2", "identity_history_missing:Q06"]
                        if rows[0][0] > d:
                            gaps += ["before_first_bar_proxy"]
                        row = dict(code=stem[2:], market=stem[:2].upper(), board=board, d=iso(d),
                                   input_key="f." + key, value="null", unit=unit, precision=precision,
                                   null_reason_or_gap=";".join(gaps), window_start="null", window_end=iso(d),
                                   valid_bars="null", list_date_source="tdx_first_bar_proxy",
                                   data_sha256_short=";".join(h[:16] for h in HASHES), first_bar_date=iso(rows[0][0]))
                        if index in (1, 6):
                            row.update(diag)
                        row.update(proxy_rows[index])
                        writer.writerow(row)
    return output.getvalue().encode("utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--day-zip", type=Path, required=True)
    parser.add_argument("--gbbq-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=HERE / "reference_values.csv")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = generate(args.day_zip, args.gbbq_zip)
    if args.check:
        require(args.output.read_bytes() == result, "reference_csv_byte_mismatch")
    else:
        args.output.write_bytes(result)
    rows = list(csv.DictReader(io.StringIO(result.decode())))
    print("PASS", "check" if args.check else "generate", len(rows), "rows; nulls:",
          dict(Counter(r["input_key"] for r in rows if r["value"] == "null")))
    print("proxy non-null:", dict(Counter(r["input_key"] for r in rows if r["proxy_value"] != "null")))


if __name__ == "__main__":
    main()
