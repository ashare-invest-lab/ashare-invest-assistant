"""#225 offline acceptance values, never a production factor adapter."""
import csv
import hashlib
import re
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_HASHES = {'formal_inputs.csv': 'a552926d8698f1111fd30e44f09d58ac5c44818b499b023ac5510f1005327f55', 'formal_calendar.csv': '8a241ed7a59669870f9be535fbbe5781ac3a7cf028d8a49c7d9ff1459d94ab20'}


def instant(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result


def load():
    for name, expected in SOURCE_HASHES.items():
        if hashlib.sha256((HERE/'sources'/name).read_bytes()).hexdigest() != expected:
            raise ValueError('formal source hash mismatch: '+name)
    inputs = {r['code']: json.loads(r['payload']) for r in
              csv.DictReader((HERE/'sources/formal_inputs.csv').open())}
    calendars = {int(r['year']): r for r in
                 csv.DictReader((HERE/'sources/formal_calendar.csv').open())}
    return inputs, calendars


def availability(record, calendars):
    """Original publication time plus the strictly next exchange trading day."""
    disclosure = date.fromisoformat(record['plrq'])
    first = instant(record['first_seen_at'])
    if disclosure.isoformat() <= record['period_end']:
        raise ValueError('invalid disclosure order')
    day = disclosure + timedelta(days=1)
    while day.year in calendars:
        cal = calendars[day.year]
        closed = any(a <= day.strftime('%m-%d') <= b
                     for a, b in json.loads(cal['closed_ranges']))
        if day.weekday() < 5 and not closed:
            return max(first, instant(day.isoformat()+'T09:30:00+08:00'),
                       instant(cal['published_at']))
        day += timedelta(days=1)
    return None


def amount(record, key, column=0):
    field = record['fields'][key]
    if not field.get('page') or not field.get('unit_page'):
        raise ValueError('missing PDF page')
    value = Decimal(field['values'][column]) * Decimal(field['multiplier'])
    if not value.is_finite():
        raise ValueError('non-finite amount')
    return value


def calculate(fid, data, calendars, d, roe, cagr):
    t = instant(d+'T15:00:00+08:00')
    records, gaps, deps = {}, [], []
    for r in data['records']:
        if instant(r['first_seen_at']) > t:
            continue
        a = availability(r, calendars)
        if a is None:
            gaps.append('calendar_not_covered')
            continue
        if a > t:
            continue
        p = r['period_end']
        if p not in records or instant(r['first_seen_at']) > instant(records[p]['first_seen_at']):
            records[p] = r
        elif instant(r['first_seen_at']) == instant(records[p]['first_seen_at']) and r != records[p]:
            gaps.append('version_conflict')
    identity = data['identity']
    identity_ok = identity and instant(identity['first_seen_at']) <= t
    if fid == 'B9':
        return 'null', ['coverage_unknown'] + ([] if identity_ok else ['identity_unknown']), [], 'null'
    if fid == 'B12':
        return 'null', ['payment_unconfirmed', 'year_unclosed', 'coverage_unknown', 'no_known_break'], [], 'null'
    value = 'null'
    annual = sorted(p for p in records if p.endswith('12-31'))
    if not data['reviewed']:
        gaps += ['unit_unverified', 'incomparable_basis']
    if fid == 'B11':
        if not identity_ok:
            gaps.append('identity_unknown')
        elif (date.fromisoformat(d) - date.fromisoformat(identity['list_date'])).days < 0:
            gaps.append('not_yet_available')
        elif d < str(int(identity['list_date'][:4])+3)+identity['list_date'][4:]:
            gaps.append('listing_under_3y')
    try:
        if not annual or not records:
            raise KeyError('anchor')
        if fid == 'B10':
            p = max(records)
            prior = str(int(p[:4])-1)+p[4:]
            fy = str(int(p[:4])-1)+'-12-31'
            oldfy = str(int(p[:4])-2)+'-12-31'
            periods = [p, prior] if p.endswith('12-31') else [p, fy, prior, oldfy]
            deps = [records[x] for x in periods if x in records]
            a, b = records[p], records[prior]
            profit = amount(a, 'np')
            if p.endswith('12-31'):
                comparable = amount(a, 'equity', 1) == amount(b, 'equity')
            else:
                f, old = records[fy], records[oldfy]
                profit += amount(f, 'np') - amount(b, 'np')
                comparable = (amount(a, 'np', 1) == amount(b, 'np') and
                              amount(a, 'equity', 1) == amount(f, 'equity') and
                              amount(b, 'equity', 1) == amount(old, 'equity') and
                              amount(f, 'equity', 1) == amount(old, 'equity'))
            value, errors = roe(profit, amount(a, 'equity'), amount(b, 'equity'))
        else:
            end = annual[-1]
            periods = [str(int(end[:4])-n)+'-12-31' for n in range(4)]
            deps = [records[x] for x in periods if x in records]
            # Intermediate years certify comparability only; the formula has two endpoints.
            a, b = records[end], records[periods[-1]]
            value, errors = cagr(amount(b, 'np'), amount(a, 'np'), periods[-1], end)
            comparable = all(amount(records[periods[n]], 'np', 1) ==
                             amount(records[periods[n+1]], 'np') for n in range(3))
        gaps += errors
        if not comparable:
            gaps.append('incomparable_basis')
        # Quarter headers often state yuan only. Currency is tied to a visible annual policy.
        currency = records[annual[-1]]
        if any(not r['currency_pages'] for r in deps):
            if not currency['currency_pages']:
                gaps.append('unit_unverified')
            elif currency not in deps:
                deps.append(currency)
    except KeyError:
        gaps.append('missing_component' if fid == 'B10' else 'missing_endpoint')
    except (ValueError, ArithmeticError):
        gaps.append('invalid_amount')
    for correction in data['corrections']:
        seen = datetime.fromtimestamp(correction['time']/1000, t.tzinfo)
        match = re.search(r'(20\d{2})年?(第一季度|第三季度|半年度|年度)', correction['title'])
        if seen > t or not match:
            continue
        period = match[1]+{'第一季度':'-03-31', '第三季度':'-09-30',
                          '半年度':'-06-30', '年度':'-12-31'}[match[2]]
        if any(r['period_end'] == period and seen > instant(r['first_seen_at']) for r in deps):
            if '报告' in correction['title'] or '财务' in correction['title']:
                gaps.append('version_conflict')
    if gaps:
        return 'null', sorted(set(gaps)), deps, 'null'
    times = [availability(r, calendars) for r in deps]
    if fid == 'B11':
        times.append(instant(identity['first_seen_at']))
    available = max(times)
    if available > t:
        return 'null', ['not_yet_available'], deps, 'null'
    return value, [], deps, available.isoformat()
