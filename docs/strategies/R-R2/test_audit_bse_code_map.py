"""R-R2离线测试；HTML/DOCX样例均为合成，不含私有样本。"""

import csv
import importlib.util
import io
import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("audit_bse_code_map", HERE / "audit_bse_code_map.py")
audit = importlib.util.module_from_spec(SPEC)
if SPEC.loader is None:
    raise RuntimeError("cannot load R-R2 audit module")
SPEC.loader.exec_module(audit)
HEADER = ["序号", "证券简称", "上市日期", "旧代码", "新代码"]
SAMPLE = [
    ["1", "甲公司", "2024/4/8", "872931", "920931"],
    ["2", "乙公司", "2024/3/29", "837023", "920123"],
    ["3", "丙公司", "2023/5/31", "430017", "920017"],
]


def html_fixture(rows: list[list[str]]) -> bytes:
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in [HEADER, *rows]
    )
    return f"<html><body><table>{body}</table></body></html>".encode()


def docx_fixture(rows: list[list[str]]) -> bytes:
    body = "".join(
        "<w:tr>"
        + "".join(
            "<w:tc><w:p><w:r><w:t>" + escape(str(cell)) + "</w:t></w:r></w:p></w:tc>"
            for cell in row
        )
        + "</w:tr>"
        for row in [HEADER, *rows]
    )
    document = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:tbl>{body}</w:tbl></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def read_csv(name: str) -> list[dict[str, str]]:
    with (HERE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class CodeMapTests(unittest.TestCase):
    def test_html_and_docx_parse_same_rows(self) -> None:
        html = audit.parse_html_map(html_fixture(SAMPLE))
        docx = audit.parse_docx_map(docx_fixture(SAMPLE))
        self.assertEqual(html, docx)
        self.assertEqual([row["new_code"] for row in html], ["920931", "920123", "920017"])
        self.assertEqual(html[1]["allocation"], "fourth_digit_adjusted")
        self.assertEqual(html[1]["simple_suffix_code"], "920023")
        with_footer = html_fixture([*SAMPLE, ["注：上市日期为原精选层挂牌日期"]])
        self.assertEqual(len(audit.parse_html_map(with_footer)), 3)

    def test_bad_table_inputs_fail_closed(self) -> None:
        cases = {
            "duplicate_old": [SAMPLE[0], SAMPLE[0]],
            "duplicate_new": [SAMPLE[0], [*SAMPLE[1][:3], "830931", "920931"]],
            "bad_prefix": [[*SAMPLE[0][:3], "600000", "920931"]],
            "bad_new_prefix": [[*SAMPLE[0][:4], "830931"]],
            "scope_date": [[*SAMPLE[0][:2], "2024/4/22", *SAMPLE[0][3:]]],
            "bad_sequence": [["2", *SAMPLE[0][1:]]],
        }
        for name, rows in cases.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.parse_html_map(html_fixture(rows))
        with self.assertRaisesRegex(ValueError, "header"):
            audit.parse_html_map(b"<html>no table</html>")

    def test_source_hash_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "public.html"
            path.write_bytes(b"public")
            source = {"id": "s", "bytes": 6, "sha256": audit.sha256(b"public")}
            self.assertTrue(audit.source_check(source, path)["matches_archived"])
            with self.assertRaisesRegex(ValueError, "SHA changed"):
                audit.source_check({**source, "sha256": "0" * 64}, path)
            with self.assertRaisesRegex(ValueError, "byte count changed"):
                audit.source_check({**source, "bytes": 5}, path)

    def test_generated_full_map_and_exceptions(self) -> None:
        rows = read_csv("bse_code_mapping.csv")
        differences = read_csv("differences.csv")
        self.assertEqual((len(rows), len(differences)), (248, 31))
        self.assertEqual(len({row["old_code"] for row in rows}), 248)
        self.assertEqual(len({row["new_code"] for row in rows}), 248)
        self.assertTrue(all(row["new_code"].startswith("920") for row in rows))
        self.assertTrue(all(row["old_code"].startswith(("43", "83", "87")) for row in rows))
        self.assertTrue(all(row["list_date"] < "2024-04-22" for row in rows))
        self.assertNotIn("switch_date", rows[0])
        by_old = {row["old_code"]: row for row in rows}
        self.assertEqual(by_old["837023"]["new_code"], "920123")
        self.assertEqual(by_old["831396"]["new_code"], "920496")
        self.assertEqual(by_old["872931"]["new_code"], "920931")
        allocation = [row for row in differences if row["category"] == "allocation_exception"]
        name_changes = [row for row in differences if row["category"] == "name_changed_vs_20241213"]
        self.assertEqual((len(allocation), len(name_changes)), (26, 5))
        for row in allocation:
            self.assertNotEqual(row["new_code"], row["simple_suffix_code"])
        changed_names = {row["old_code"]: row["name"] for row in name_changes}
        self.assertEqual(
            changed_names,
            {
                "830879": "基康技术",
                "831834": "三维装备",
                "835305": "*ST云创",
                "838810": "春光智能",
                "839680": "*ST广道",
            },
        )
        self.assertIn("DOCX简称=基康仪器", name_changes[0]["note"])

    def test_generated_result_and_sources(self) -> None:
        result = json.loads((HERE / "check_result.json").read_text(encoding="utf-8"))
        self.assertEqual(
            result["counts"],
            {
                "mappings": 248,
                "old_prefix": {"43": 16, "83": 178, "87": 54},
                "suffix_preserved": 222,
                "fourth_digit_adjusted": 26,
                "html_docx_mismatches": 5,
                "html_docx_name_differences": 5,
                "html_docx_code_or_date_mismatches": 0,
                "differences": 31,
            },
        )
        self.assertEqual(len(result["comparison"]["mismatches"]), 5)
        self.assertTrue(
            all(item["changed_fields"] == ["name"] for item in result["comparison"]["mismatches"])
        )
        self.assertEqual(len(result["notice_checks"]), 4)
        self.assertTrue(
            all(marker for item in result["notice_checks"] for marker in item["markers"].values())
        )
        self.assertEqual(len(result["source_checks"]), 6)
        self.assertTrue(all(item["matches_archived"] for item in result["source_checks"]))

    def test_public_source_registry(self) -> None:
        registry = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
        self.assertEqual(len(registry["sources"]), 6)
        self.assertEqual(
            {item["id"] for item in registry["sources"]},
            set(audit.NOTICE_MARKERS) | {"bse_code_map_html", "bse_code_map_docx"},
        )
        for item in registry["sources"]:
            parsed = urlsplit(item["url"])
            self.assertEqual((parsed.scheme, parsed.hostname), ("https", "www.bse.cn"))
            self.assertFalse(parsed.username or parsed.password)
            self.assertGreater(item["bytes"], 0)
            self.assertEqual(item["http_status"], 200)
            self.assertRegex(item["sha256"], re.compile(r"^[0-9a-f]{64}$"))
            self.assertNotIn("cookie", json.dumps(item).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
