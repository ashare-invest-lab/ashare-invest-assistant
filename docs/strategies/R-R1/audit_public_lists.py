"""R-R1：仅用交易所公开文件核对当前ST与终止上市名单。

离线核验sources.json绑定的六份公开响应及两份旧深交所公开XLSX；
--write生成名单和差异。公开抓取时刻、URL与原始SHA见sources.json。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
import warnings
from collections import Counter
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
STRATEGIES = HERE.parent
SZ_A = ("000", "001", "002", "003", "300", "301", "302")
SH_A = ("600", "601", "603", "605", "688", "689")
DIFF_FIELDS = [
    "exchange",
    "category",
    "change",
    "symbol",
    "event_date",
    "old_snapshot",
    "new_snapshot",
    "name_before",
    "name_after",
    "old_value",
    "new_value",
    "source",
    "note",
]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def norm(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def risk_flag(name):
    text = norm(name).upper()
    if text.startswith("*ST"):
        return "*ST"
    if text.startswith("ST"):
        return "ST"
    if "退" in text:
        return "退"
    return "非ST"


def day(value):
    text = str(value or "")[:10]
    parsed = date.fromisoformat(text)
    return parsed.isoformat()


def compact_day(value):
    text = str(value or "").strip()
    if re.fullmatch(r"\d{8}", text):
        text = f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return day(text)


def workbook_rows(path, header):
    import openpyxl

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Workbook contains no default style")
        wb = openpyxl.load_workbook(path, data_only=True)
        rows = list(wb.active.iter_rows(values_only=True))
        wb.close()
    require(rows and list(rows[0]) == header, f"unexpected workbook header: {path}")
    return rows[1:]


def read_sz_names(path):
    rows = workbook_rows(
        path, ["变更日期", "证券代码", "证券简称", "变更前简称", "变更后简称"]
    )
    events = []
    for order, row in enumerate(rows):
        if row[0] is None or row[1] is None:
            continue
        code = str(row[1]).strip().zfill(6)
        require(re.fullmatch(r"\d{6}", code) is not None, "invalid SZ symbol")
        event = {
            "date": day(row[0]),
            "code": code,
            "current": norm(row[2]),
            "before": norm(row[3]),
            "after": norm(row[4]),
            "order": order,
        }
        require(event["after"] or event["current"], "empty changed name")
        events.append(event)
    require(events, "empty SZ name-change table")
    return events


def read_sz_termination(path):
    rows = workbook_rows(path, ["证券代码", "证券简称", "上市日期", "终止上市日期"])
    result = {}
    for row in rows:
        if not row[0]:
            continue
        code = str(row[0]).strip().zfill(6)
        require(
            re.fullmatch(r"\d{6}", code) is not None and code not in result,
            "invalid/duplicate SZ termination",
        )
        result[code] = {
            "name": norm(row[1]),
            "list_date": day(row[2]),
            "delisting_date": day(row[3]),
        }
    require(result, "empty SZ termination table")
    return result


def read_sse(path, stock_type, current):
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = payload.get("result")
    require(isinstance(rows, list) and rows, f"empty SSE result: {path}")
    require(
        payload.get("pageHelp", {}).get("total") == len(rows), "SSE page is incomplete"
    )
    result = {}
    for row in rows:
        require(str(row.get("STOCK_TYPE")) == stock_type, "SSE board mismatch")
        code = str(row.get("A_STOCK_CODE") or "")
        require(
            re.fullmatch(r"\d{6}", code) is not None and code.startswith(SH_A),
            "invalid SSE A/CDR code",
        )
        require(code not in result, "duplicate SSE code")
        name = norm(row.get("SEC_NAME_CN") if current else row.get("COMPANY_ABBR"))
        name = name or norm(row.get("COMPANY_ABBR"))
        result[code] = {
            "code": code,
            "name": name,
            "flag": risk_flag(name),
            "security_type": "cdr"
            if stock_type == "8" and code.startswith("689")
            else "stock",
            "board": "main" if stock_type == "1" else "star",
            "list_date": compact_day(row.get("LIST_DATE")),
        }
        if not current:
            result[code]["delisting_date"] = compact_day(row.get("DELIST_DATE"))
    return result


def sz_current(events, terminations, as_of):
    latest = {}
    for event in sorted(events, key=lambda item: (item["date"], item["order"])):
        if event["code"].startswith(SZ_A) and event["date"] <= as_of:
            latest[event["code"]] = event
    current = {}
    for code, event in latest.items():
        terminated = terminations.get(code)
        if terminated and terminated["delisting_date"] <= as_of:
            continue
        name = event["after"] or event["current"]
        current[code] = {
            "name": name,
            "flag": risk_flag(name),
            "event_date": event["date"],
        }
    return current


def event_key(event):
    return event["date"], event["code"], event["before"], event["after"]


def source_check(source, path):
    raw = path.read_bytes()
    require(len(raw) <= 3_000_000, "public response too large")
    require(len(raw) == source["bytes"], f"byte count changed: {source['id']}")
    require(sha256(raw) == source["sha256"], f"SHA changed: {source['id']}")
    return {
        "id": source["id"],
        "bytes": len(raw),
        "sha256": sha256(raw),
        "matches_archived": sha256(raw) == source["sha256"],
    }


def make_diff(
    old_events,
    new_events,
    old_terms,
    new_terms,
    old_current,
    new_current,
    old_asof,
    new_asof,
    sh_st_count,
    sh_asof,
):
    diffs = []
    old_counter, new_counter = (
        Counter(map(event_key, old_events)),
        Counter(map(event_key, new_events)),
    )
    by_key = {event_key(event): event for event in new_events + old_events}
    for change, keys in (
        ("added", new_counter - old_counter),
        ("removed", old_counter - new_counter),
    ):
        for key in sorted(keys.elements()):
            event = by_key[key]
            diffs.append(
                {
                    "exchange": "SZ",
                    "category": "name_change",
                    "change": change,
                    "symbol": event["code"],
                    "event_date": event["date"],
                    "old_snapshot": old_asof,
                    "new_snapshot": new_asof,
                    "name_before": event["before"],
                    "name_after": event["after"],
                    "old_value": "",
                    "new_value": "",
                    "source": "szse_name_change",
                    "note": "简称事件差分；不等同ST切换",
                }
            )
    for change, codes in (
        ("added", new_terms.keys() - old_terms.keys()),
        ("removed", old_terms.keys() - new_terms.keys()),
    ):
        terms = new_terms if change == "added" else old_terms
        for code in sorted(codes):
            row = terms[code]
            diffs.append(
                {
                    "exchange": "SZ",
                    "category": "termination",
                    "change": change,
                    "symbol": code,
                    "event_date": row["delisting_date"],
                    "old_snapshot": old_asof,
                    "new_snapshot": new_asof,
                    "name_before": "",
                    "name_after": row["name"],
                    "old_value": "",
                    "new_value": row["delisting_date"],
                    "source": "szse_termination",
                    "note": "A/B股原始表全量差分；当前A股名单另过滤",
                }
            )
    for code in sorted(old_terms.keys() & new_terms.keys()):
        if old_terms[code] != new_terms[code]:
            diffs.append(
                {
                    "exchange": "SZ",
                    "category": "termination",
                    "change": "field_changed",
                    "symbol": code,
                    "event_date": new_terms[code]["delisting_date"],
                    "old_snapshot": old_asof,
                    "new_snapshot": new_asof,
                    "name_before": old_terms[code]["name"],
                    "name_after": new_terms[code]["name"],
                    "old_value": json.dumps(
                        old_terms[code], ensure_ascii=False, sort_keys=True
                    ),
                    "new_value": json.dumps(
                        new_terms[code], ensure_ascii=False, sort_keys=True
                    ),
                    "source": "szse_termination",
                    "note": "同一代码字段变化",
                }
            )
    for code in sorted(old_current.keys() | new_current.keys()):
        old = old_current.get(code, {"name": "", "flag": "无记录"})
        new = new_current.get(
            code, {"name": "", "flag": "已终止" if code in new_terms else "无记录"}
        )
        if old["flag"] != new["flag"]:
            diffs.append(
                {
                    "exchange": "SZ",
                    "category": "current_status",
                    "change": "changed",
                    "symbol": code,
                    "event_date": new_terms.get(code, {}).get("delisting_date", ""),
                    "old_snapshot": old_asof,
                    "new_snapshot": new_asof,
                    "name_before": old["name"],
                    "name_after": new["name"],
                    "old_value": old["flag"],
                    "new_value": new["flag"],
                    "source": "szse_name_change+szse_termination",
                    "note": "退与ST分列；已终止不留在当前简称状态表",
                }
            )
    if sh_st_count != 81:
        diffs.append(
            {
                "exchange": "SH",
                "category": "st_aggregate",
                "change": "count_changed",
                "symbol": "",
                "event_date": "",
                "old_snapshot": "2026-11-01",
                "new_snapshot": sh_asof,
                "name_before": "",
                "name_after": "",
                "old_value": "81",
                "new_value": str(sh_st_count),
                "source": "security_master.md+sse_current_main+sse_current_star",
                "note": "仅历史汇总数对比；无旧逐代码快照，不推断具体新增/摘帽股票",
            }
        )
    return diffs


def audit(raw_dir, old_name_path, old_term_path):
    registry = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    for relative, expected in registry["reference_files"].items():
        require(
            sha256((STRATEGIES / relative).read_bytes()) == expected,
            f"reference changed: {relative}",
        )
    for key, path in (
        ("old_szse_name_change", old_name_path),
        ("old_szse_termination", old_term_path),
    ):
        require(
            sha256(path.read_bytes())
            == registry["archived_public_inputs"][key]["sha256"],
            f"old public input changed: {key}",
        )
    by_id = {source["id"]: source for source in registry["sources"]}
    sh_asof = by_id["sse_current_main"]["fetched_at"][:10]
    paths = {key: raw_dir / source["file"] for key, source in by_id.items()}
    checks = [source_check(source, paths[key]) for key, source in by_id.items()]
    old_events, new_events = (
        read_sz_names(old_name_path),
        read_sz_names(paths["szse_name_change"]),
    )
    old_terms, new_terms = (
        read_sz_termination(old_term_path),
        read_sz_termination(paths["szse_termination"]),
    )
    old_asof = max(
        max(row["date"] for row in old_events),
        max(row["delisting_date"] for row in old_terms.values()),
    )
    new_asof = max(
        max(row["date"] for row in new_events),
        max(row["delisting_date"] for row in new_terms.values()),
    )
    old_current, new_current = (
        sz_current(old_events, old_terms, old_asof),
        sz_current(new_events, new_terms, new_asof),
    )
    sh_current = read_sse(paths["sse_current_main"], "1", True) | read_sse(
        paths["sse_current_star"], "8", True
    )
    sh_terms = read_sse(paths["sse_termination_main"], "1", False) | read_sse(
        paths["sse_termination_star"], "8", False
    )
    st_rows = [
        {
            "exchange": "SZ",
            "symbol": code,
            "name": row["name"],
            "flag": row["flag"],
            "as_of": new_asof,
            "source": "szse_name_change+szse_termination",
        }
        for code, row in sorted(new_current.items())
        if row["flag"] in {"ST", "*ST"}
    ]
    sh_st_rows = [
        {
            "exchange": "SH",
            "symbol": code,
            "name": row["name"],
            "flag": row["flag"],
            "as_of": sh_asof,
            "source": "sse_current_main+sse_current_star",
        }
        for code, row in sorted(sh_current.items())
        if row["flag"] in {"ST", "*ST"} and row["security_type"] == "stock"
    ]
    st_rows += sh_st_rows
    sz_term_rows = [
        {
            "exchange": "SZ",
            "symbol": code,
            "name": row["name"],
            "list_date": row["list_date"],
            "delisting_date": row["delisting_date"],
            "source": "szse_termination",
        }
        for code, row in sorted(new_terms.items())
        if code.startswith(SZ_A)
    ]
    sh_term_rows = [
        {
            "exchange": "SH",
            "symbol": code,
            "name": row["name"],
            "list_date": row["list_date"],
            "delisting_date": row["delisting_date"],
            "source": "sse_termination_main+sse_termination_star",
        }
        for code, row in sorted(sh_terms.items())
        if row["security_type"] == "stock"
    ]
    termination_rows = sz_term_rows + sh_term_rows
    termination_map = {
        (row["exchange"], row["symbol"]): row["delisting_date"]
        for row in termination_rows
    }
    listing = json.loads(
        (STRATEGIES / "T-R65/manifests/listing_history_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    references = {
        (exchange, code): value
        for exchange, code, value in listing["stats"]["fallback_stocks"]
    }
    with (STRATEGIES / "S2-7/termination_public_subset.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        references.update(
            {
                (row["exchange"], row["symbol"]): row["delisting_date"]
                for row in csv.DictReader(handle)
            }
        )
    mismatches = [
        {
            "exchange": exchange,
            "symbol": code,
            "reference": value,
            "current": termination_map.get((exchange, code)),
        }
        for (exchange, code), value in sorted(references.items())
        if termination_map.get((exchange, code)) != value
    ]
    diffs = make_diff(
        old_events,
        new_events,
        old_terms,
        new_terms,
        old_current,
        new_current,
        old_asof,
        new_asof,
        len(sh_st_rows),
        sh_asof,
    )
    for mismatch in mismatches:
        exchange, code = mismatch["exchange"], mismatch["symbol"]
        current_row = (
            sh_terms.get(code, {}) if exchange == "SH" else new_terms.get(code, {})
        )
        diffs.append(
            {
                "exchange": exchange,
                "category": "termination_date_mismatch",
                "change": "source_conflict",
                "symbol": code,
                "event_date": mismatch["current"] or "",
                "old_snapshot": "public_notice",
                "new_snapshot": sh_asof if exchange == "SH" else new_asof,
                "name_before": current_row.get("name", ""),
                "name_after": current_row.get("name", ""),
                "old_value": mismatch["reference"],
                "new_value": mismatch["current"] or "missing",
                "source": "S2-7/termination_public_subset.csv+current_exchange_termination_list",
                "note": "公告摘牌日与交易所当前DELIST_DATE冲突；双值保留，不改写来源",
            }
        )
    sh_reference_count = sum(exchange == "SH" for exchange, _ in references)
    sz_a_old = {code: row for code, row in old_terms.items() if code.startswith(SZ_A)}
    sz_a_new = {code: row for code, row in new_terms.items() if code.startswith(SZ_A)}
    result = {
        "mode": "offline_archived_bytes",
        "as_of": {"SZ": new_asof, "SH_fetch_date": sh_asof},
        "source_checks": checks,
        "counts": {
            "sz_name_events_old_new": [len(old_events), len(new_events)],
            "sz_termination_a_old_new": [len(sz_a_old), len(sz_a_new)],
            "sz_current_st_old_new": [
                sum(row["flag"] in {"ST", "*ST"} for row in old_current.values()),
                sum(row["flag"] in {"ST", "*ST"} for row in new_current.values()),
            ],
            "sh_current_main_star": [
                sum(row["board"] == "main" for row in sh_current.values()),
                sum(row["board"] == "star" for row in sh_current.values()),
            ],
            "sh_current_st": len(sh_st_rows),
            "sh_termination": len(sh_term_rows),
            "current_st_total": len(st_rows),
            "current_termination_total": len(termination_rows),
            "current_st_by_exchange_flag": {
                exchange: dict(
                    sorted(
                        Counter(
                            row["flag"]
                            for row in st_rows
                            if row["exchange"] == exchange
                        ).items()
                    )
                )
                for exchange in ("SH", "SZ")
            },
            "current_termination_by_exchange": dict(
                sorted(Counter(row["exchange"] for row in termination_rows).items())
            ),
            "current_cdr_excluded": sum(
                row["security_type"] == "cdr" for row in sh_current.values()
            ),
        },
        "reference_checks": {
            "termination_records": len(references),
            "mismatches": mismatches,
            "sh_600543_expected_actual": ["*ST", sh_current["600543"]["flag"]],
            "t_r65_sh_termination_expected_actual": [148, len(sh_term_rows)],
        },
        "differences": diffs,
        "limits": [
            "深市为两份旧新公开XLSX全量差分；沪市旧ST仅有2026-11-01汇总数，不能逐项还原81→80。",
            f"沪市终止名单新快照为全量，旧记录仅核manifest与S2公开子集的{sh_reference_count}个键，不冒充148项逐项旧新比较。",
            "深市当前ST由官方简称变更派生并剔除已终止；ST/*ST与退、已终止分列。",
            "不读原337行CSV、数据库、私有样本或真实持仓；不做F23准确率、策略、r2或交易判读。",
        ],
    }
    require(sh_current["600543"]["flag"] == "*ST", "600543 reference mismatch")
    return result, st_rows, termination_rows, diffs


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--old-szse-name", type=Path, required=True)
    parser.add_argument("--old-szse-termination", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="写入核对名单与差异")
    args = parser.parse_args()
    try:
        result, st_rows, termination_rows, diffs = audit(
            args.raw_dir, args.old_szse_name, args.old_szse_termination
        )
        if args.write:
            write_csv(
                HERE / "st_current.csv",
                ["exchange", "symbol", "name", "flag", "as_of", "source"],
                st_rows,
            )
            write_csv(
                HERE / "termination_current.csv",
                ["exchange", "symbol", "name", "list_date", "delisting_date", "source"],
                termination_rows,
            )
            write_csv(HERE / "differences.csv", DIFF_FIELDS, diffs)
            (HERE / "check_result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
                newline="\n",
            )
        print(
            json.dumps(
                {
                    "counts": result["counts"],
                    "differences": len(diffs),
                    "reference_checks": result["reference_checks"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"R-R1 audit failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
