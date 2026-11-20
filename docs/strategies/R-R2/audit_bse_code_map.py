"""R-R2：北交所920新旧代码公开对照的抓取、复核与差异生成。

原始公开响应只写--raw-dir指定的仓库外目录；仓库内仅保存来源元数据、
规范化清单和差异。未使用cookie、证书、数据库、私有样本或真实交易数据。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

HERE = Path(__file__).resolve().parent
CUTOVER = "2024-04-22"
SOURCES = (
    {
        "id": "bse_code_map_html",
        "file": "code_mapping.html",
        "url": "https://www.bse.cn/service/code_mapping.html",
        "publisher": "北京证券交易所：新旧代码对照表",
    },
    {
        "id": "bse_code_map_docx",
        "file": "code_mapping_20241213.docx",
        "url": "https://www.bse.cn/uploads/6/file/public/202412/20241213164135_pio0sowwqn.docx",
        "publisher": "北证公告〔2024〕231号附件：存量上市公司股票新旧代码对照表",
    },
    {
        "id": "bse_2024_code_guideline",
        "file": "notice_20240419.html",
        "url": "https://www.bse.cn/important_news/200021617.html",
        "publisher": "北证公告〔2024〕20号",
    },
    {
        "id": "bse_2024_switch_preparation",
        "file": "notice_20241213.html",
        "url": "https://www.bse.cn/important_news/200024109.html",
        "publisher": "北证公告〔2024〕231号",
    },
    {
        "id": "bse_2024_switch_explainer",
        "file": "explainer_20241213.html",
        "url": "https://www.bse.cn/important_news/200024115.html",
        "publisher": "北京证券交易所：北交所启动存量上市公司代码切换工作",
    },
    {
        "id": "bse_2025_switch_launch",
        "file": "notice_20250912.html",
        "url": "https://www.bse.cn/important_news/200026735.html",
        "publisher": "北证公告〔2025〕46号",
    },
)
NOTICE_MARKERS = {
    "bse_2024_code_guideline": ("自2024年4月22日起施行", "920号段"),
    "bse_2024_switch_preparation": (
        "2024年4月22日以前上市",
        "后三位保持不变",
        "第四位代码做递进处理",
    ),
    "bse_2024_switch_explainer": ("248家", "后三位不变", "逐家对第四位代码做递进"),
    "bse_2025_switch_launch": ("自2025年10月9日起", "新旧代码对应关系"),
}
MAP_FIELDS = (
    "source_seq",
    "name",
    "list_date",
    "old_code",
    "new_code",
    "simple_suffix_code",
    "allocation",
)
DIFF_FIELDS = (
    "category",
    "source_seq",
    "name",
    "list_date",
    "old_code",
    "new_code",
    "simple_suffix_code",
    "note",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def iso_day(value: object) -> str:
    text = str(value or "").strip().replace("/", "-")
    return datetime.strptime(text, "%Y-%m-%d").date().isoformat()


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            require(self._row is None, "nested HTML row")
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            require(self._cell is None, "nested HTML cell")
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            if self._row is None:
                raise ValueError("HTML cell outside row")
            self._row.append(norm("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def normalize_table(rows: list[list[str]]) -> list[dict[str, object]]:
    header = ["序号", "证券简称", "上市日期", "旧代码", "新代码"]
    starts = [index for index, row in enumerate(rows) if row[:5] == header]
    require(len(starts) == 1, "expected exactly one code-map header")
    result: list[dict[str, object]] = []
    for row in rows[starts[0] + 1 :]:
        if not any(row):
            continue
        if result and not row[0].isdigit():
            break  # 官网表尾“注”是注释，不是证券数据。
        require(len(row) >= 5 and row[0].isdigit(), "unexpected code-map row")
        require(int(row[0]) == len(result) + 1, "non-consecutive source sequence")
        old_code, new_code = row[3], row[4]
        require(re.fullmatch(r"\d{6}", old_code) is not None, "invalid old code")
        require(re.fullmatch(r"\d{6}", new_code) is not None, "invalid new code")
        require(old_code.startswith(("43", "83", "87")), "old-code prefix")
        require(new_code.startswith("920"), "new-code prefix")
        require(old_code != new_code and norm(row[1]), "identity mapping or empty name")
        list_date = iso_day(row[2])
        require(list_date < CUTOVER, "mapping scope must predate 2024-04-22")
        simple = f"920{old_code[-3:]}"
        result.append(
            {
                "source_seq": len(result) + 1,
                "name": norm(row[1]),
                "list_date": list_date,
                "old_code": old_code,
                "new_code": new_code,
                "simple_suffix_code": simple,
                "allocation": "suffix_preserved" if new_code == simple else "fourth_digit_adjusted",
            }
        )
    require(result, "empty code-map table")
    require(len({row["old_code"] for row in result}) == len(result), "duplicate old code")
    require(len({row["new_code"] for row in result}) == len(result), "duplicate new code")
    return result


def parse_html_map(raw: bytes) -> list[dict[str, object]]:
    parser = TableParser()
    parser.feed(raw.decode("utf-8-sig", errors="strict"))
    parser.close()
    return normalize_table(parser.rows)


def parse_docx_map(raw: bytes) -> list[dict[str, object]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        require("word/document.xml" in archive.namelist(), "DOCX document missing")
        info = archive.getinfo("word/document.xml")
        require(info.file_size <= 3_000_000, "DOCX document too large")
        document = archive.read(info)
        # Stdlib-only parser: input is a fixed public DOCX with archived hash and size caps.
        root = ElementTree.fromstring(document)  # noqa: S314
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    rows: list[list[str]] = []
    for table in root.findall(".//w:tbl", ns):
        for tr in table.findall("./w:tr", ns):
            row = [
                norm("".join(node.text or "" for node in tc.findall(".//w:t", ns)))
                for tc in tr.findall("./w:tc", ns)
            ]
            if row:
                rows.append(row)
    return normalize_table(rows)


def fetch_public(raw_dir: Path) -> dict[str, object]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for source in SOURCES:
        source_url = urllib.parse.urlsplit(source["url"])
        require(
            source_url.scheme == "https"
            and source_url.hostname == "www.bse.cn"
            and not (source_url.username or source_url.password),
            "unexpected public source URL",
        )
        request = urllib.request.Request(  # noqa: S310
            source["url"], headers={"User-Agent": "aia-public-research/1"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            raw = response.read(3_000_001)
            final_url = response.geturl()
            status = response.status
        require(status == 200 and len(raw) <= 3_000_000, "public fetch failed/too large")
        parsed = urllib.parse.urlsplit(final_url)
        require(
            parsed.scheme == "https" and parsed.hostname == "www.bse.cn",
            "unexpected redirect host",
        )
        require(raw, "empty public response")
        (raw_dir / source["file"]).write_bytes(raw)
        records.append(
            {
                **source,
                "fetched_at": datetime.now(UTC).isoformat(),
                "http_status": status,
                "bytes": len(raw),
                "sha256": sha256(raw),
            }
        )
        time.sleep(0.2)
    manifest = {"sources": records}
    (raw_dir / "fetch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return manifest


def source_check(source: dict[str, object], path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    require(len(raw) == source["bytes"], f"byte count changed: {source['id']}")
    require(sha256(raw) == source["sha256"], f"SHA changed: {source['id']}")
    return {
        "id": source["id"],
        "bytes": len(raw),
        "sha256": sha256(raw),
        "matches_archived": True,
    }


def audit(
    raw_dir: Path,
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, object]]]:
    manifest_path = raw_dir / "fetch_manifest.json"
    registry = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists()
        else json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    )
    sources = registry["sources"]
    require([item["id"] for item in sources] == [item["id"] for item in SOURCES], "source registry")
    checks = [source_check(item, raw_dir / item["file"]) for item in sources]
    raw_by_id = {item["id"]: (raw_dir / item["file"]).read_bytes() for item in sources}
    html_rows = parse_html_map(raw_by_id["bse_code_map_html"])
    docx_rows = parse_docx_map(raw_by_id["bse_code_map_docx"])
    require(len(html_rows) == len(docx_rows) == 248, "expected 248 mappings")
    html_by_old = {row["old_code"]: row for row in html_rows}
    docx_by_old = {row["old_code"]: row for row in docx_rows}
    mismatches = []
    for old_code in sorted(html_by_old.keys() | docx_by_old.keys()):
        left, right = html_by_old.get(old_code), docx_by_old.get(old_code)
        fields = ("name", "list_date", "new_code")
        if left is None or right is None or any(left[key] != right[key] for key in fields):
            changed = [
                key for key in fields if left is None or right is None or left[key] != right[key]
            ]
            mismatches.append(
                {"old_code": old_code, "changed_fields": changed, "html": left, "docx": right}
            )
    code_or_date = [
        item for item in mismatches if set(item["changed_fields"]) & {"list_date", "new_code"}
    ]
    require(not code_or_date, "HTML/DOCX code or list-date mismatch")
    notice_checks = []
    for source_id, markers in NOTICE_MARKERS.items():
        text = raw_by_id[source_id].decode("utf-8-sig", errors="strict")
        found = {marker: marker in text for marker in markers}
        require(all(found.values()), f"notice marker missing: {source_id}")
        notice_checks.append({"id": source_id, "markers": found})
    name_differences = []
    for item in mismatches:
        current, original = item["html"], item["docx"]
        name_differences.append(
            {
                "category": "name_changed_vs_20241213",
                **{key: current[key] for key in DIFF_FIELDS if key in current},
                "note": (
                    f"2024-12-13 DOCX简称={original['name']}；"
                    f"当前HTML简称={current['name']}；代码与上市日期一致"
                ),
            }
        )
    allocation_differences = [
        {
            "category": "allocation_exception",
            **{key: row[key] for key in DIFF_FIELDS if key in row},
            "note": "新码不是920+旧码后三位；按官网逐行值交付，不用公式改写",
        }
        for row in html_rows
        if row["allocation"] == "fourth_digit_adjusted"
    ]
    differences = name_differences + allocation_differences
    require(len(allocation_differences) == 26, "expected 26 published allocation exceptions")
    result = {
        "mode": "offline_archived_public_bytes",
        "scope": "Current BSE HTML table compared row-by-row with the 2024-12-13 official DOCX",
        "source_checks": checks,
        "notice_checks": notice_checks,
        "counts": {
            "mappings": len(html_rows),
            "old_prefix": dict(sorted(Counter(row["old_code"][:2] for row in html_rows).items())),
            "suffix_preserved": sum(row["allocation"] == "suffix_preserved" for row in html_rows),
            "fourth_digit_adjusted": len(allocation_differences),
            "html_docx_mismatches": len(mismatches),
            "html_docx_name_differences": len(name_differences),
            "html_docx_code_or_date_mismatches": len(code_or_date),
            "differences": len(differences),
        },
        "comparison": {"mismatches": mismatches},
        "differences": differences,
        "limits": [
            "上市日期来自对照表，不是代码切换日期；本清单不提供逐股切换日。",
            "248行是2024-04-22以前上市的存量公司历史对照，不代表当前仍在市。",
            "新码只取官网逐行值，不用920+旧码后三位推导；未做当前在市名单或麦蕊核验。",
        ],
    }
    return result, html_rows, differences


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="仅抓取固定北交所公开URL")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        if args.fetch:
            fetch_public(args.raw_dir)
        result, rows, differences = audit(args.raw_dir)
        if args.write:
            manifest_path = args.raw_dir / "fetch_manifest.json"
            registry_path = manifest_path if manifest_path.exists() else HERE / "sources.json"
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            (HERE / "sources.json").write_text(
                json.dumps(registry, ensure_ascii=False, indent=2),
                encoding="utf-8",
                newline="\n",
            )
            write_csv(HERE / "bse_code_mapping.csv", MAP_FIELDS, rows)
            write_csv(HERE / "differences.csv", DIFF_FIELDS, differences)
            (HERE / "check_result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
                newline="\n",
            )
        print(json.dumps({"counts": result["counts"]}, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(f"R-R2 audit failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
