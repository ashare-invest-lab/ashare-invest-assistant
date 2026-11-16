#!/usr/bin/env python3
"""T-A197 contract v1.0: frozen public snapshots, offline proxies, no network."""
import argparse
import csv
import hashlib
import io
import json
import struct
import zipfile
from bisect import bisect_right
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATES = ('2026-06-30', '2026-09-30', '2026-11-09')
FEATURES = {
    'B9': ('fin_report_count', 'count', (1, 2)),
    'B10': ('roe_ttm', 'pct', (1, 3)),
    'B11': ('profit_cagr_3y', 'pct', (3, 4, 5)),
    'B12': ('dividend_continuous_years', 'years', (6, 7, 8, 9)),
}
SOURCE_SHA = '057dc4d4644e74cbbb3ac65a7811e0a50417bf29c23f2ecea471f4e05b96543f'
PROXY_SHA = '755d2a8ee8b90bd2b31b45339d0a1ae1e96578cb4629fa510f023fc5d72fc3a4'
GBBQ_SHA = 'c1cbc818d748079aa79749393729dbcf378adf258a22734762d19b885ed0eeab'
SLICE_SHA = {
    'calendar.csv': '1be8c10beb9a9c09de8a9d7360a7f8ab341a64ecd492d04e911bd51e90f8d261',
    'listings.csv': 'bf9fd90ec0475de73e967679eae70304e93fd0f02b33794b5d4f56da5ba1010b',
}
FIELDS = ('code,market,as_of,feature,input_key,value,unit,status,fq_basis,null_reason,'
          'available_at,source_ids,source_url,proxy_value,proxy_available_at,proxy_flags,'
          'ex_date_proxy_years,ex_date_proxy_null_reasons,'
          'cash_distribution_plus_buyback_years,cash_distribution_plus_buyback_null_reasons').split(',')
BAR = struct.Struct('<IIIIIfII')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def iso(n):
    return date(n // 10000, n // 100 % 100, n % 100).isoformat()


def rounded(value):
    return format(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP), 'f')


def reports(data, kind, calendar, d, listing='0001-01-01'):
    found = {}
    # Fixed full-statement endpoints only; forecasts, flashes and summaries are not inputs.
    for period, notice, amount, *extra in data[kind]['rows']:
        period, notice = period[:10], notice[:10] if notice else ''
        if (period > d or not notice or notice > d or notice <= period
                or period < listing or notice < listing):
            continue
        require(period[5:] in ('03-31', '06-30', '09-30', '12-31'), 'unknown period')
        if kind == 'income' and extra and extra[0] != '001':
            continue
        pos = bisect_right(calendar, notice)
        if not calendar or notice < calendar[0] or pos == len(calendar) or calendar[pos] > d:
            continue
        available = calendar[pos] + 'T09:30:00+08:00'
        candidate = (notice, available, amount, extra)
        require(period not in found or found[period] == candidate, 'version conflict: ' + period)
        found[period] = candidate
    return found


def roe(profit, equity_end, equity_start):
    values = [profit, equity_end, equity_start]
    if any(v is None for v in values):
        return 'null', ['missing_component']
    p, e, b = map(Decimal, values)
    if not all(v.is_finite() for v in (p, e, b)):
        return 'null', ['invalid_amount']
    avg = (e + b) / 2
    gaps = (['equity_end_nonpositive'] if e <= 0 else [])
    gaps += ['equity_avg_nonpositive'] if avg <= 0 else []
    return ('null', gaps) if gaps else (rounded(100 * p / avg), [])


def cagr(base, end, base_period, end_period):
    gaps = []
    span = (int(end_period[:4]) - int(base_period[:4])) * 12
    span += int(end_period[5:7]) - int(base_period[5:7])
    if span != 36 or end_period[8:] != base_period[8:]:
        gaps.append('invalid_span')
    if base is None or end is None:
        return 'null', gaps + ['missing_endpoint']
    b, e = Decimal(base), Decimal(end)
    if not b.is_finite() or not e.is_finite():
        return 'null', gaps + ['invalid_amount']
    gaps += ['base_nonpositive'] if b <= 0 else []
    gaps += ['end_zero'] if e == 0 else ['end_negative'] if e < 0 else []
    return (('null', gaps) if gaps else
            (rounded(100 * ((e / b) ** (Decimal(1) / 3) - 1)), []))


def dividend_gaps(data, income, calendar, d):
    # This public snapshot has no payment/completion, annual-closure or event-coverage fields.
    # Never infer closure, an explicit zero year, attribution or a payment from an ex-date.
    annual = sorted(p for p in income if p.endswith('12-31'))
    visible = [r for r in data['dividend']['rows'] if r[1] and r[1][:10] <= d and r[0][:10] <= d]
    years = set()
    for period, notice, ex_date, status, cash in visible:
        pos = bisect_right(calendar, notice[:10])
        if not calendar or notice[:10] < calendar[0] or pos == len(calendar) or calendar[pos] > d:
            continue
        if status == '实施分配' and ex_date and ex_date[:10] < d and cash is not None:
            amount = Decimal(cash)
            if amount.is_finite() and amount > 0:
                years.add(period[:4])
    common = ['coverage_unknown', 'year_unclosed', 'no_known_break']
    if not annual:
        common.append('no_complete_year')
    # Opt-B changes event timing only; it does not waive F-Q07/F-Q08 closure and coverage.
    return ['payment_unconfirmed'] + common, common, sorted(years)


def proxy(fid, data, calendar, d, listing):
    inc = reports(data, 'income', calendar, d, listing if fid == 'B9' else '0001-01-01')
    flags = ['proxy_only', 'T_R86_applicability_pending', 'T_A197_contract_v1.0',
             'calendar_proxy=sh000001_bars', 'listing_first_bar_proxy', 'restated_value_risk']
    gaps, value, deps = [], 'null', []
    ex_gaps, years = [], []
    if fid == 'B9':
        flags += ['distinct_period_end', 'scope_snapshot_unverified']
        value = str(len(inc)) if inc else 'null'
        gaps = [] if inc else ['coverage_unknown']
        if any(r[2] is None for r in inc.values()):
            gaps.append('missing_component')
        if any(r[2] is not None and not Decimal(r[2]).is_finite() for r in inc.values()):
            gaps.append('invalid_amount')
        deps = list(inc.values())
    elif fid == 'B10':
        flags += ['comparability_unverified', 'source_semantics_unverified']
        bal = reports(data, 'balance', calendar, d)
        if not inc:
            gaps = ['missing_component']
        else:
            p = max(inc)
            prior = str(int(p[:4]) - 1) + p[4:]
            fy = str(int(p[:4]) - 1) + '-12-31'
            periods = [p] if p.endswith('12-31') else [p, fy, prior]
            deps = [inc[t] for t in periods if t in inc] + [bal[t] for t in (p, prior) if t in bal]
            flags.append('components=' + '|'.join(periods) + ';equity=' + p + '|' + prior)
            if any(t not in inc or inc[t][2] is None for t in periods) or any(t not in bal for t in (p, prior)):
                gaps = ['missing_component']
            elif any(bal[t][3] != ['CNY'] for t in (p, prior)):
                gaps = ['unit_unverified']
            else:
                np = [Decimal(inc[t][2]) for t in periods]
                if not all(v.is_finite() for v in np):
                    gaps = ['invalid_amount']
                else:
                    ttm = np[0] if len(np) == 1 else np[0] + np[1] - np[2]
                    value, gaps = roe(ttm, bal[p][2], bal[prior][2])
    elif fid == 'B11':
        flags += ['annual_endpoints', 'comparability_unverified']
        annual = sorted(p for p in inc if p.endswith('12-31'))
        if not annual:
            gaps = ['missing_endpoint']
        else:
            end = annual[-1]
            base = str(int(end[:4]) - 3) + '-12-31'
            deps = [inc[t] for t in (base, end) if t in inc]
            value, gaps = cagr(inc.get(base, (None, None, None))[2], inc[end][2], base, end)
            flags.append('endpoints=' + base + '|' + end)
        if int(d.replace('-', '')) < int(listing.replace('-', '')) + 30000:
            gaps.append('listing_under_3y')
    else:
        gaps, ex_gaps, years = dividend_gaps(data, inc, calendar, d)
        flags += ['payment_completion_required', 'fiscal_year', 'cash_only_no_buybacks',
                  'observed_ex_cash_years=' + '|'.join(years)]
    if listing > d:
        gaps.append('not_yet_available')
        flags.append('before_first_bar_proxy')
    if data['code'].startswith('92'):
        flags.append('HG2')
        value = 'null'
    if gaps:
        value = 'null'
    flags += ['gap=' + g for g in sorted(set(gaps))]
    available = max((r[1] for r in deps), default='null') if value != 'null' else 'null'
    return value, available, ';'.join(flags), ';'.join(ex_gaps)


def generate(inputs, ledger, calendar, listings):
    rows = []
    for data in inputs:
        code = data['code']
        market = 'BJ' if code.startswith('92') else 'SH' if code.startswith('6') else 'SZ'
        for d in DATES:
            for fid, (key, unit, questions) in FEATURES.items():
                kinds = {'B9': ['income'], 'B10': ['income', 'balance'], 'B11': ['income'], 'B12': ['dividend']}[fid]
                evidence = [r for r in ledger if r['code'] == code and r['kind'] in kinds]
                require(evidence and all(r['first_seen_at'] == 'null' and r['available_at'] == 'null' for r in evidence),
                        'new formal evidence requires review')
                gaps = ['missing_visibility'] + {
                    'B9': ['coverage_unknown', 'identity_unknown'],
                    'B10': ['source_semantics_unverified', 'unit_unverified', 'incomparable_basis'],
                    'B11': ['source_semantics_unverified', 'unit_unverified', 'incomparable_basis', 'identity_unknown'],
                    'B12': ['source_semantics_unverified', 'payment_unconfirmed', 'year_unclosed', 'coverage_unknown', 'no_known_break'],
                }[fid]
                value, available, flags, ex_gaps = proxy(fid, data, calendar, d, listings[code])
                row = dict.fromkeys(FIELDS, 'null')
                row.update(code=code, market=market, as_of=d+'T15:05:00+08:00', feature=fid,
                           input_key='f.'+key, unit=unit, status='依 T-A197（契约 v1.0）',
                           fq_basis=';'.join(f'F-Q{q:02}:Opt-A' for q in questions),
                           null_reason=';'.join(gaps), source_ids=';'.join(r['source_id'] for r in evidence),
                           source_url=';'.join(dict.fromkeys(r['source_url'] for r in evidence)),
                           proxy_value=value, proxy_available_at=available, proxy_flags=flags)
                if fid == 'B12':
                    row['ex_date_proxy_null_reasons'] = ex_gaps
                    row['cash_distribution_plus_buyback_null_reasons'] = 'missing_component;coverage_unknown'
                rows.append(row)
    return rows


def extract_days(path, inputs):
    with zipfile.ZipFile(path) as archive:
        members = {n.replace('\\', '/'): n for n in archive.namelist()}
        def days(stem):
            raw = archive.read(members[f'{stem[:2]}/lday/{stem}.day'])
            require(raw and len(raw) % BAR.size == 0, 'truncated bars')
            result = [iso(r[0]) for r in BAR.iter_unpack(raw)]
            require(result == sorted(set(result)), 'unordered/duplicate bars')
            return result
        full = days('sh000001')
        listings = {x['code']: days(('bj' if x['code'].startswith('92') else 'sh'
                    if x['code'].startswith('6') else 'sz') + x['code'])[0] for x in inputs}
    # Retain the lower-bound guard and every possible visible notice's successor.
    # This sparse calendar is valid only for the pinned proxy inputs and DATES.
    selected = {full[0]}
    for data in inputs:
        for kind in ('income', 'balance', 'dividend'):
            for row in data[kind]['rows']:
                notice = row[1][:10] if row[1] else ''
                pos = bisect_right(full, notice)
                if full[0] <= notice <= max(DATES) and pos < len(full) and full[pos] <= max(DATES):
                    selected.add(full[pos])
    return sorted(selected), listings


def market_inputs(args, inputs, ledger):
    if args.gbbq_zip:
        require(sha256(args.gbbq_zip) == GBBQ_SHA, 'gbbq hash mismatch')
        # No gbbq field is read by B9–B12; absence of a slice is not zero dividends.
        with zipfile.ZipFile(args.gbbq_zip) as archive:
            require('gbbq' in archive.namelist(), 'missing gbbq member')
    if args.day_zip:
        require(sha256(args.day_zip) == next(r['sha256'] for r in ledger if r['kind'] == 'day_zip'),
                'day hash mismatch')
        calendar, listings = extract_days(args.day_zip, inputs)
        if args.extract_inputs:
            args.input_dir.mkdir(parents=True, exist_ok=True)
            for name, fields, rows in (
                ('calendar.csv', ['trade_date'], ((d,) for d in calendar)),
                ('listings.csv', ['code', 'first_bar_date'], sorted(listings.items())),
            ):
                with (args.input_dir/name).open('w', encoding='utf-8', newline='') as stream:
                    writer = csv.writer(stream, lineterminator='\n')
                    writer.writerow(fields)
                    writer.writerows(rows)
        return calendar, listings
    require(not args.extract_inputs, '--extract-inputs requires --day-zip')
    for name, expected in SLICE_SHA.items():
        require(sha256(args.input_dir/name) == expected, 'slice hash mismatch: ' + name)
    with (args.input_dir/'calendar.csv').open(encoding='utf-8', newline='') as stream:
        calendar = [r['trade_date'] for r in csv.DictReader(stream)]
    with (args.input_dir/'listings.csv').open(encoding='utf-8', newline='') as stream:
        listings = {r['code']: r['first_bar_date'] for r in csv.DictReader(stream)}
    require(calendar and calendar == sorted(set(calendar)), 'unordered/duplicate calendar')
    require(set(listings) == {x['code'] for x in inputs}, 'listing sample mismatch')
    return calendar, listings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--day-zip', type=Path, help='从冻结原包重新抽取日线日期；默认使用仓库内 CSV')
    parser.add_argument('--gbbq-zip', type=Path, help='核验冻结权息原包；当前财务计算无权息字段依赖')
    parser.add_argument('--input-dir', type=Path, default=HERE/'inputs')
    parser.add_argument('--extract-inputs', action='store_true', help='配合 --day-zip 将切片写入 --input-dir')
    parser.add_argument('--rules', type=Path, help='legacy CLI argument; unused by finance')
    parser.add_argument('--sources', type=Path, default=HERE/'sources/public_sources.csv')
    parser.add_argument('--output', type=Path, default=HERE/'reference_values.csv')
    parser.add_argument('--features', nargs='+', choices=FEATURES, default=list(FEATURES))
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    require(not (args.check and args.extract_inputs), '--check cannot write input slices')
    path = HERE/'sources/proxy_inputs.jsonl'
    require(sha256(args.sources) == SOURCE_SHA and sha256(path) == PROXY_SHA, 'source hash mismatch')
    ledger = list(csv.DictReader(args.sources.open()))
    inputs = [json.loads(s) for s in path.read_text().splitlines()]
    calendar, listings = market_inputs(args, inputs, ledger)
    with localcontext() as ctx:
        ctx.prec = 50
        rows = generate(inputs, ledger, calendar, listings)
    if set(args.features) != set(FEATURES):
        old = list(csv.DictReader(args.output.open()))
        identity = lambda r: (r['code'], r['as_of'], r['feature'])
        require(list(map(identity, old)) == list(map(identity, rows)), 'row identities changed')
        rows = [new if new['feature'] in args.features else prev for prev, new in zip(old, rows)]
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, FIELDS, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    output = stream.getvalue().encode()
    if args.check:
        require(args.output.read_bytes() == output, 'reference CSV differs')
    else:
        args.output.write_bytes(output)
    print(f'OK: {len(rows)} rows; contract v1.0; formal nulls and isolated proxies reproduced')


if __name__ == '__main__':
    main()
