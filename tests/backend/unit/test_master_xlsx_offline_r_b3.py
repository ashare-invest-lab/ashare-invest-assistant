"""Synthetic in-memory XLSX boundaries; no exchange files or external services."""

from __future__ import annotations

import io
import socket
import zipfile
from xml.etree.ElementTree import ParseError

import pytest
from app.master import xlsx

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("XLSX unit tests must not access the network")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def archive(parts: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as stream:
        for name, content in parts.items():
            stream.writestr(name, content)
    return output.getvalue()


def sheet(rows: str) -> str:
    return f'<worksheet xmlns="{NS}"><sheetData>{rows}</sheetData></worksheet>'


def workbook(rows: str, shared: str | None = None) -> bytes:
    parts = {"xl/worksheets/sheet1.xml": sheet(rows)}
    if shared is not None:
        parts["xl/sharedStrings.xml"] = f'<sst xmlns="{NS}">{shared}</sst>'
    return archive(parts)


@pytest.mark.parametrize("payload", [b"", b"synthetic-not-a-zip"])
def test_non_zip_is_a_domain_error(payload: bytes) -> None:
    with pytest.raises(xlsx.XlsxError, match="不是 xlsx 文件") as error:
        xlsx.read_rows(payload)
    assert isinstance(error.value.__cause__, zipfile.BadZipFile)


def test_unrelated_xml_is_not_mistaken_for_a_worksheet() -> None:
    data = archive({"xl/worksheets/sheetA.xml": sheet(""), "notes.xml": "<note/>"})
    with pytest.raises(xlsx.XlsxError, match="xlsx 没有工作表"):
        xlsx.read_rows(data)


def test_numeric_sheet_order_uses_first_sheet_only() -> None:
    data = archive(
        {
            "xl/worksheets/sheet10.xml": sheet("<row><c><v>10</v></c></row>"),
            "xl/worksheets/sheet2.xml": sheet("<row><c><v>2</v></c></row>"),
            "xl/worksheets/sheet3.xml": "invalid XML in unused sheet",
        }
    )
    assert xlsx.read_rows(data) == [["2"]]


def test_sparse_columns_rich_shared_and_inline_strings_keep_text() -> None:
    data = workbook(
        '<row><c r="A1" t="s"><v>0</v></c>'
        '<c r="C1" t="inlineStr"><is><r><t>内联</t></r><r><t>文本</t></r></is></c>'
        '<c r="AA1"><v>001.2300</v></c></row>',
        "<si><r><t>共享</t></r><r><t>文本</t></r><r><t/></r></si>",
    )
    expected = [""] * 27
    expected[0], expected[2], expected[26] = "共享文本", "内联文本", "001.2300"
    assert xlsx.read_rows(data) == [expected]


def test_empty_cells_missing_references_and_blank_rows() -> None:
    data = workbook(
        '<row/><row><c t="s"/><c t="s"><v/></c>'
        '<c t="inlineStr"/><c t="inlineStr"><is><t/></is></c>'
        "<c/><c><v/></c><c><v>0</v></c></row>"
    )
    assert xlsx.read_rows(data) == [["", "", "", "", "", "", "0"]]


@pytest.mark.parametrize(
    "index,shared",
    [
        ("0", None),
        ("1", "<si><t>only</t></si>"),
        ("not-integer", "<si><t>only</t></si>"),
    ],
)
def test_shared_index_failures_are_domain_errors(
    index: str, shared: str | None
) -> None:
    with pytest.raises(xlsx.XlsxError, match="共享字符串索引越界") as error:
        xlsx.read_rows(workbook(f'<row><c t="s"><v>{index}</v></c></row>', shared))
    assert isinstance(error.value.__cause__, (ValueError, IndexError))


@pytest.mark.parametrize("reference", ["1A", "a1", "?1"])
def test_unrecognized_explicit_column_is_rejected(reference: str) -> None:
    with pytest.raises(xlsx.XlsxError, match="单元格引用无法识别"):
        xlsx.read_rows(workbook(f'<row><c r="{reference}"><v>1</v></c></row>'))


@pytest.mark.parametrize("part", ["sheet", "shared"])
def test_each_xml_part_limit_rejects_before_parsing(
    monkeypatch: pytest.MonkeyPatch,
    part: str,
) -> None:
    monkeypatch.setattr(xlsx, "_MAX_PART", 32)
    data = workbook(
        "" if part == "shared" else "synthetic" * 10,
        "<si><t>synthetic</t></si>" if part == "shared" else None,
    )
    with pytest.raises(xlsx.XlsxError, match="xlsx 部件过大"):
        xlsx.read_rows(data)


def test_exact_part_limit_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    content = sheet("<row><c><v>7</v></c></row>")
    monkeypatch.setattr(xlsx, "_MAX_PART", len(content.encode()))
    assert xlsx.read_rows(archive({"xl/worksheets/sheet1.xml": content})) == [["7"]]


@pytest.mark.parametrize("part", ["sheet", "shared"])
def test_malformed_selected_xml_is_not_silently_empty(part: str) -> None:
    parts = {"xl/worksheets/sheet1.xml": "<broken" if part == "sheet" else sheet("")}
    if part == "shared":
        parts["xl/sharedStrings.xml"] = "<broken"
    with pytest.raises(ParseError):
        xlsx.read_rows(archive(parts))
