"""COV-T6: synthetic byte-level decoding contracts; no files or external resources."""

from __future__ import annotations

import socket

import pytest

from app.importing import decoding

pytestmark = pytest.mark.unit
BOM = b"\xef\xbb\xbf"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        pytest.fail("decoding test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def test_normalize_encoding_aliases_and_unknown() -> None:
    assert decoding.normalize_encoding(" utf8 ") == "utf-8"
    assert decoding.normalize_encoding("GB2312") == "gbk"
    assert decoding.normalize_encoding("cp936") == "gbk"
    assert decoding.normalize_encoding("gb18030") == "gb18030"
    assert decoding.normalize_encoding("synthetic-unknown") is None


def test_split_lines_strips_bom_and_preserves_unterminated_tail() -> None:
    lines = decoding.split_lines(BOM + b"alpha\r\nbeta\rgamma\nlast")

    assert [(line.row_no, line.data, line.has_newline) for line in lines] == [
        (1, b"alpha", True),
        (2, b"beta", True),
        (3, b"gamma", True),
        (4, b"last", False),
    ]


def test_decode_honors_explicit_encoding_override() -> None:
    result = decoding.decode("合成文本".encode("gb18030"), override="gb18030")

    assert result.encoding == "gb18030"
    assert result.confidence == 1.0
    assert [(line.row_no, line.text) for line in result.lines] == [(1, "合成文本")]


def test_decode_bom_selects_utf8_sig() -> None:
    result = decoding.decode(BOM + "合成文本\r\n".encode())

    assert result.encoding == "utf-8-sig"
    assert result.confidence == 1.0
    assert [(line.text, line.has_newline) for line in result.lines] == [
        ("合成文本", True)
    ]


def test_decode_ascii_fast_path() -> None:
    result = decoding.decode(b"alpha\r\nbeta\r\n")

    assert result.encoding == "utf-8"
    assert result.confidence == 1.0
    assert [line.text for line in result.lines] == ["alpha", "beta"]


def test_decode_truncated_final_utf8_line_remains_row_level_error() -> None:
    result = decoding.decode(b"alpha\r\n\xf0\x9f")

    assert result.encoding == "utf-8"
    assert result.confidence == 1.0
    assert [(line.row_no, line.text, line.has_newline) for line in result.lines] == [
        (1, "alpha", True),
        (2, None, False),
    ]
    assert result.lines[1].data == b"\xf0\x9f"


def test_decode_gbk_fallback_returns_decoded_lines_and_confidence() -> None:
    result = decoding.decode("合成文本".encode("gbk"))

    assert result.encoding == "gbk"
    assert result.confidence == 0.2
    assert [line.text for line in result.lines] == ["合成文本"]


def test_decode_rejects_excess_body_decode_failures() -> None:
    result = decoding.decode(b"\xff\r\n")

    assert result.encoding is None
    assert result.confidence is None
    assert [(line.row_no, line.text, line.data) for line in result.lines] == [
        (1, None, b"\xff")
    ]


def test_decode_rejects_implausible_fallback_characters() -> None:
    result = decoding.decode("α".encode("gbk"))

    assert result.encoding is None
    assert result.confidence is None
    assert [line.text for line in result.lines] == [None]
