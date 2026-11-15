"""Nine offline tests; fixtures are synthetic and contain no private sample."""
import csv
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("audit_public_lists", HERE / "audit_public_lists.py")
audit = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit)
RAW = Path("F:/workspace/team/reports/R-R1/public-raw-v1")
OLD_NAME = Path("F:/tdata-st-research/szse_name_change_20261110.xlsx")
OLD_TERM = Path("F:/tdata-st-research/szse_delist.xlsx")


def event(code, before, after, date="2026-11-01", order=0):
    return {"date": date, "code": code, "current": after,
            "before": before, "after": after, "order": order}


def termination(code, name="公开退", delisting_date="2026-11-13"):
    return {code: {"name": name, "list_date": "2010-01-01", "delisting_date": delisting_date}}


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class AuditTests(unittest.TestCase):
    def test_registry_and_hashes(self):
        registry = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(len(registry["sources"]), 6)
        for source in registry["sources"]:
            self.assertNotIn("cookie", str(source).lower())
            path = RAW / source["file"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), source["sha256"])
            self.assertTrue(audit.source_check(source, path)["matches_archived"])
        for relative, expected in registry["reference_files"].items():
            path = HERE.parent / relative
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)
        with self.assertRaisesRegex(ValueError, "SHA changed"):
            audit.source_check({**registry["sources"][0], "sha256": "0" * 64}, RAW / "szse_name_change.xlsx")

    def test_public_urls(self):
        registry = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
        sources = registry["sources"] + list(registry["archived_public_inputs"].values())
        self.assertEqual(len({item["id"] for item in registry["sources"]}), 6)
        for item in sources:
            parsed = urlsplit(item["url"])
            self.assertEqual(parsed.scheme, "https")
            self.assertIn(parsed.hostname, {"www.szse.cn", "query.sse.com.cn"})
            self.assertFalse(parsed.username or parsed.password)
            self.assertIn(parsed.port, (None, 443))

    def test_st_prefix_only(self):
        self.assertEqual(audit.risk_flag("ST公开"), "ST")
        self.assertEqual(audit.risk_flag("*ST公开"), "*ST")
        self.assertEqual(audit.risk_flag(" *ＳＴ公开"), "*ST")
        self.assertEqual(audit.risk_flag("退公开"), "退")
        self.assertEqual(audit.risk_flag("公开ST"), "非ST")

    def test_dates_and_event_keys(self):
        self.assertEqual(audit.day("2014-11-04 00:00:00"), "2014-11-04")
        self.assertEqual(audit.compact_day("20141104"), "2014-11-04")
        self.assertEqual(audit.compact_day("2026-11-13"), "2026-11-13")
        with self.assertRaises(ValueError):
            audit.compact_day("2026-13-13")
        self.assertEqual(audit.event_key(event("1", "甲", "乙")), ("2026-11-01", "1", "甲", "乙"))

    def test_sz_current_and_termination_exclusion(self):
        rows = [event("000001", "公开", "ST公开"), event("000002", "*ST公开", "公开"),
                event("000003", "退公开", "退公开")]
        current = audit.sz_current(rows, termination("000003"), "2026-11-13")
        self.assertEqual(current["000001"]["flag"], "ST")
        self.assertEqual(current["000002"]["flag"], "非ST")
        self.assertNotIn("000003", current)
        self.assertEqual(audit.sz_current(rows, {}, "2026-10-31"), {})
        with self.assertRaisesRegex(KeyError, "order"):
            audit.sz_current([{"code": "000001", "date": "2026-11-01"}], {}, "2026-11-13")

    def test_name_termination_and_status_differences(self):
        old_events = [event("000001", "公开", "ST公开"),
                      event("300901", "中胤时尚", "中胤时尚", "2026-10-01")]
        new_events = old_events + [event("300901", "中胤时尚", "中胤科技", "2026-11-12")]
        old_terms = termination("000001", delisting_date="2020-01-01")
        new_terms = {**old_terms, **termination("002731", "萃华退")}
        old_current = audit.sz_current(old_events, old_terms, "2026-11-01")
        new_current = audit.sz_current(new_events, new_terms, "2026-11-13")
        diffs = audit.make_diff(old_events, new_events, old_terms, new_terms,
                                old_current, new_current, "2026-11-01", "2026-11-13", 81, "2026-11-15")
        self.assertEqual([(row["category"], row["change"], row["symbol"]) for row in diffs],
                         [("name_change", "added", "300901"), ("termination", "added", "002731")])
        changed_terms = {**new_terms, "000001": dict(new_terms["000001"], delisting_date="2020-01-02")}
        changed = audit.make_diff([], [], old_terms, changed_terms, {}, {}, "旧", "新", 80, "2026-11-15")
        self.assertEqual({row["change"] for row in changed}, {"added", "field_changed", "count_changed"})

    def test_sse_current_termination_and_cdr(self):
        main = {"result": [{"STOCK_TYPE": "1", "A_STOCK_CODE": "600190", "SEC_NAME_CN": "*ST公开",
                            "COMPANY_ABBR": "公开", "LIST_DATE": "19990507"}], "pageHelp": {"total": 1}}
        terminated = {"result": [{"STOCK_TYPE": "1", "A_STOCK_CODE": "600190", "COMPANY_ABBR": "退市锦港",
                                  "LIST_DATE": "19990507", "DELIST_DATE": "20250728"}], "pageHelp": {"total": 1}}
        with tempfile.TemporaryDirectory() as temporary:
            current_path, term_path = Path(temporary) / "current.json", Path(temporary) / "term.json"
            current_path.write_text(json.dumps(main), encoding="utf-8")
            term_path.write_text(json.dumps(terminated), encoding="utf-8")
            current = audit.read_sse(current_path, "1", True)["600190"]
            term = audit.read_sse(term_path, "1", False)["600190"]
            with self.assertRaisesRegex(ValueError, "SSE board mismatch"):
                audit.read_sse(current_path, "8", True)
        self.assertEqual((current["flag"], current["board"]), ("*ST", "main"))
        self.assertEqual((term["delisting_date"], term["security_type"]), ("2025-07-28", "stock"))

    def test_real_archive_audit(self):
        result, st_rows, termination_rows, diffs = audit.audit(RAW, OLD_NAME, OLD_TERM)
        self.assertTrue(all(item["matches_archived"] for item in result["source_checks"]))
        self.assertEqual((len(st_rows), len(termination_rows), len(diffs)), (193, 338, 6))
        self.assertEqual(result["counts"]["sz_name_events_old_new"], [7503, 7505])
        self.assertEqual(result["counts"]["sz_termination_a_old_new"], [189, 190])
        self.assertEqual(result["reference_checks"]["termination_records"], 90)
        self.assertEqual(result["reference_checks"]["mismatches"][0]["symbol"], "600190")
        self.assertEqual(result["reference_checks"]["sh_600543_expected_actual"], ["*ST", "*ST"])

    def test_cli_reproduction_and_generated_lists(self):
        command = [sys.executable, "-I", "-B", str(HERE / "audit_public_lists.py"),
                   "--raw-dir", str(RAW), "--old-szse-name", str(OLD_NAME),
                   "--old-szse-termination", str(OLD_TERM), "--write"]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        st_rows = read_csv(HERE / "st_current.csv")
        termination_rows = read_csv(HERE / "termination_current.csv")
        difference_rows = read_csv(HERE / "differences.csv")
        self.assertEqual((len(st_rows), len(termination_rows), len(difference_rows)), (193, 338, 6))
        self.assertTrue(all(row["flag"] in {"ST", "*ST"} for row in st_rows))
        self.assertTrue(all(len(row["symbol"]) == 6 and row["symbol"].isdigit() for row in termination_rows))
        st_keys = {(row["exchange"], row["symbol"]) for row in st_rows}
        term_keys = {(row["exchange"], row["symbol"]) for row in termination_rows}
        self.assertTrue(st_keys.isdisjoint(term_keys))
        result = json.loads((HERE / "check_result.json").read_text(encoding="utf-8"))
        self.assertEqual(result["counts"]["current_st_total"], 193)


if __name__ == "__main__":
    unittest.main(verbosity=2)
