#!/usr/bin/env python3
"""U11 offline descriptive calibration; numpy only, no system suggestions.

All signal filters and regimes use <=T. Future endpoints are labels, not
features. D1 whole-day execution screens are reported ONLY as retrospective
conditional diagnostics; daily bars cannot certify opening fills.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import random
import re
import tempfile
import zipfile

import numpy as np

START, SPLIT, END = 20150101, 20201231, 20261110
SEED = 80  # Full enumeration: no random subsampling or fitted cutoffs.
BANDS = {1: 1.0, 5: 2.0, 20: 5.0}
MULTIPLIERS = (0.5, 0.75, 1.0, 1.5, 2.0)
STOCK = re.compile(r"(?:sh(?:60[0135]|688)|sz(?:00[0123]|30[01]))\d{3}\.day$")
DTYPE = np.dtype([(n, t) for n, t in (
    ("date", "<u4"), ("open", "<u4"), ("high", "<u4"),
    ("low", "<u4"), ("close", "<u4"), ("amount", "<f4"),
    ("vol", "<u4"), ("reserved", "<u4"))])


def verify_archive(archive, sums):
    matches = [line.split()[0] for line in sums.read_text().splitlines()
               if len(line.split()) == 2
               and line.split()[1].lstrip("*") == archive.name]
    if len(matches) != 1:
        raise ValueError("archive requires exactly one SHA256SUMS entry")
    with archive.open("rb") as f:
        actual = hashlib.file_digest(f, "sha256").hexdigest()
    if actual != matches[0]:
        raise ValueError("archive SHA256SUMS mismatch")
    return actual


def read_day(z, member, scratch):
    # Flatten only explicitly selected basenames, never extract arbitrary paths.
    p = scratch / member.replace("\\", "/").split("/")[-1]
    p.write_bytes(z.read(member))
    if p.stat().st_size % DTYPE.itemsize:
        raise ValueError("partial 32-byte record")
    a = np.fromfile(p, dtype=DTYPE)
    p.unlink()
    if len(a) and (np.any(np.diff(a["date"].astype(np.int64)) <= 0)
                   or np.any(a["date"] < 19900101)):
        raise ValueError("invalid or non-increasing dates")
    return a[a["date"] <= END]


def valid_bar(a):
    return ((a["low"] > 0) & (a["low"] <= a["open"])
            & (a["low"] <= a["close"]) & (a["open"] <= a["high"])
            & (a["close"] <= a["high"]))


def summarize(e, band):
    n = len(e)
    if not n:
        return {"n": 0}
    ab = np.abs(e)
    buy, sell = float(np.mean(e > 0)), float(np.mean(e < 0))
    rate = float(np.mean(ab <= band))
    return {
        "n": n, "hold_rate": rate, "buy_add_rate": buy,
        "sell_rate": sell, "zero_rate": float(np.mean(e == 0)),
        "abs_e_pp_p25_p50_p75": np.quantile(ab, [0.25, 0.5, 0.75]).tolist(),
        "band_percentile": 100 * rate,
        "sensitivity_rates": [float(np.mean(ab <= band * m)) for m in MULTIPLIERS],
        "comparable_bands_pp": {
            "at_buy_rate": float(np.quantile(ab, buy)),
            "at_sell_rate": float(np.quantile(ab, sell)),
            "at_midpoint_rate": float(np.quantile(ab, (buy + sell) / 2)),
        },
    }


def group_masks(t, dates, regimes):
    yield "all", np.ones(len(t), dtype=bool)
    yield "IS", dates[t] <= SPLIT
    yield "OOS", dates[t] > SPLIT
    for year in range(2015, 2027):
        yield str(year), dates[t] // 10000 == year
    for state, name in enumerate(("down", "flat", "up")):
        state_mask = regimes[t] == state
        yield name, state_mask
        for period, mask in (("IS", dates[t] <= SPLIT), ("OOS", dates[t] > SPLIT)):
            yield period + "/" + name, state_mask & mask
        for year in range(2015, 2027):
            yield str(year) + "/" + name, state_mask & (dates[t] // 10000 == year)


def collect(z, scratch):
    members = sorted(z.namelist())
    names = {n: n.replace("\\", "/").split("/")[-1] for n in members}
    indices = [n for n in members if names[n] == "sh000300.day"]
    if len(indices) != 1:
        raise ValueError("expected one sh000300.day")
    bm = read_day(z, indices[0], scratch)
    if len(bm) < 21 or not np.all(valid_bar(bm)):
        raise ValueError("invalid benchmark OHLC")
    dates = bm["date"]
    if dates[-1] != END or dates[20] >= START:
        raise ValueError("benchmark must cover fixed dates plus regime warmup")
    regimes = np.full(len(bm), -1, dtype=np.int8)
    r20 = bm["close"][20:] / bm["close"][:-20] - 1
    regimes[20:] = np.where(r20 < -0.05, 0, np.where(r20 > 0.05, 2, 1))
    members = [n for n in members if STOCK.fullmatch(names[n])]
    if len({names[n] for n in members}) != len(members):
        raise ValueError("duplicate stock file")
    counts = Counter(stock_files=len(members))
    audit = {h: Counter() for h in BANDS}
    values = {h: [] for h in BANDS}
    times = {h: [] for h in BANDS}
    execution = {h: [] for h in BANDS}
    min_date, max_date = END, 0
    for member in members:
        a = read_day(z, member, scratch)
        counts["stock_rows"] += len(a)
        if not len(a):
            counts["empty_files"] += 1
            continue
        min_date = min(min_date, int(a["date"][0]))
        max_date = max(max_date, int(a["date"][-1]))
        valid = valid_bar(a)
        counts["invalid_stock_bars"] += int(np.sum(~valid))
        # First 60 valid observed bars, including T: conservative listing proxy.
        seasoned = np.cumsum(valid) >= 60
        idx = np.searchsorted(dates, a["date"])
        matched = (idx < len(bm)) & (dates[np.minimum(idx, len(bm) - 1)] == a["date"])
        counts["rows_outside_benchmark_calendar"] += int(np.sum(~matched))
        rows = np.flatnonzero(matched)
        aligned = np.zeros(len(bm), dtype=DTYPE)
        aligned[idx[rows]] = a[rows]
        present = aligned["date"] > 0
        age_ok = np.zeros(len(bm), dtype=bool)
        age_ok[idx[rows]] = seasoned[rows]
        valid_t = valid_bar(aligned)
        research = (dates >= START) & (dates <= END) & (regimes >= 0)
        # Sequential T-only exclusion ledger; missing != proven suspension.
        mask = research & present
        counts["present_T"] += int(mask.sum())
        for label, good in (("invalid_T", valid_t), ("under_60_bars_T", age_ok),
                            ("zero_volume_T", aligned["vol"] > 0),
                            ("one_price_T", aligned["high"] > aligned["low"])):
            counts[label] += int(np.sum(mask & ~good))
            mask &= good
        counts["eligible_T"] += int(mask.sum())
        counts["stocks_with_eligible_T"] += int(mask.any())
        for h in BANDS:
            c = audit[h]
            ts = np.flatnonzero(mask)
            c["eligible_T"] += len(ts)
            mature = ts + h < len(bm)
            c["not_matured"] += int(np.sum(~mature))
            ts = ts[mature]
            # Purge IS labels crossing split; OOS starts at T>=2021-01-01.
            cross = (dates[ts] <= SPLIT) & (dates[ts + h] > SPLIT)
            c["split_purged"] += int(cross.sum())
            ts = ts[~cross]
            entry, target = aligned[ts + 1], aligned[ts + h]
            # Missing labels are counted, never imputed/forward-filled.
            entry_ok = (entry["date"] > 0) & (entry["open"] > 0)
            target_ok = (target["date"] > 0) & (target["close"] > 0)
            c["missing_entry_open"] += int(np.sum(~entry_ok))
            c["missing_target_close_after_entry"] += int(np.sum(entry_ok & ~target_ok))
            known = entry_ok & target_ok
            ts, entry, target = ts[known], entry[known], target[known]
            e = 100 * ((target["close"] / entry["open"] - 1)
                       - (bm["close"][ts + h] / bm["open"][ts + 1] - 1))
            # Retrospective outcome annotation, NEVER a T-known signal feature.
            good_entry = valid_bar(entry) & (entry["vol"] > 0)
            screened = good_entry & (entry["high"] > entry["low"])
            c["entry_bad_bar_or_zero_volume"] += int(np.sum(~good_entry))
            c["entry_one_price_after_valid"] += int(np.sum(good_entry & ~screened))
            c["pit_endpoint_n"] += len(e)
            c["execution_screened_n"] += int(screened.sum())
            values[h].append(e)
            times[h].append(ts.astype(np.int32))
            execution[h].append(screened)
    horizons = {}
    for h, band in BANDS.items():
        if not values[h]:
            raise ValueError("no stock observations")
        e, t, ex = np.concatenate(values[h]), np.concatenate(times[h]), np.concatenate(execution[h])
        groups, conditional = {}, {}
        for name, mask in group_masks(t, dates, regimes):
            groups[name] = summarize(e[mask], band)
            conditional[name] = summarize(e[mask & ex], band)
        horizons[str(h)] = {
            "band_pp": band, "audit": dict(audit[h]),
            "signal_date_range": [int(dates[t].min()), int(dates[t].max())],
            "entry_date_range": [int(dates[t + 1].min()), int(dates[t + 1].max())],
            "target_date_range": [int(dates[t + h].min()), int(dates[t + h].max())],
            "pit_endpoint_groups": groups,
            "retrospective_execution_groups": conditional,
        }
    return {
        "counts": dict(counts), "stock_raw_date_range": [min_date, max_date],
        "benchmark_date_range": [int(dates[0]), int(dates[-1])],
        "benchmark_sessions": len(bm), "horizons": horizons,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--sha256sums", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    random.seed(SEED)
    sha = verify_archive(args.archive, args.sha256sums)
    with tempfile.TemporaryDirectory(prefix="u11-") as tmp:
        with zipfile.ZipFile(args.archive) as z:
            result = collect(z, Path(tmp))
    result["protocol"] = {
        "conclusion": "证据不足", "system_hold_samples": 0,
        "archive": args.archive.name, "sha256": sha, "verified_against": "SHA256SUMS",
        "fixed_seed": SEED, "sampling": "all eligible stock x T; equal observation weights",
        "signal_start": START, "split_inclusive_IS": SPLIT, "data_end": END,
        "adjustment": "none; ex-rights/dividend discontinuities NOT corrected by price ratios",
        "calendar": "sh000300 observed sessions proxy, not certified exchange calendar",
        "regime": "close(T)/close(T-20)-1: down < -5%, flat [-5%,5%], up >5%",
        "universe": "archive SH 600/601/603/605/688, SZ 000/001/002/003/300/301; no BJ/B/CDR",
        "ST": "unidentifiable in .day; retained, no current-name backfill",
        "listing_age": "at least 60 valid observed bars through T; no listing master",
        "T_filters": "valid OHLC, age proxy, positive volume, high>low; <=T only",
        "returns": "100*((stock close(Dh)/open(D1)-1)-(CSI300 close(Dh)/open(D1)-1))",
        "pit_endpoint_groups": "T-known pool, available open/close outcome labels only",
        "retrospective_execution_groups": "conditional diagnostic excluding D1 invalid/zero-volume/one-price; NOT PIT selection",
        "execution_limit": "daily OHLC cannot establish 09:30 fills; missing != suspension; one-price != proven limit-lock",
        "split_purge": "exclude T<=20201231 with Dh>20201231; no IS/OOS holding-window overlap",
        "sensitivity_multipliers": MULTIPLIERS, "quantiles": "numpy linear exact empirical quantiles",
        "comparability": "hold overlaps buy/sell; comparable bands target their separate marginal rates, not 1/3 classes",
        "inference": "descriptive census; overlapping windows and cross-stock dependence, no IID p-values/CI",
        "limitations": "snapshot survivor/coverage/revision bias; no point-in-time source metadata; no proxy signal",
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True,
                                      indent=2, allow_nan=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
