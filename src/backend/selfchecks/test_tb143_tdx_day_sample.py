"""T-B143：合成 zip 离线导出，不连库、不出网。"""

import csv
import hashlib
import io
import json
from zipfile import ZipFile

import pytest

from app.ingest.tdx_local import DAY_LAYOUT
from probes.tb143_tdx_day_sample import main, to_code


@pytest.mark.parametrize(("market", "num", "expected"), [
    ("sh", "600000", "600000.SH"), ("sh", "688001", "688001.SH"),
    ("sz", "300750", "300750.SZ"), ("sz", "301001", "301001.SZ"),
    ("sz", "302001", "302001.SZ"), ("bj", "430047", "430047.BJ"),
    ("bj", "830799", "830799.BJ"), ("bj", "870204", "870204.BJ"),
    ("bj", "920000", "920000.BJ"), ("sh", "000001", None),
    ("sz", "399001", None), ("sz", "200002", None),
    ("sh", "900901", None), ("sh", "920000", None),
    ("sh", "60000", None), ("sh", "60000x", None),
    ("SH", "600000", None), ("sh", "６０００００", None),
])
def test_to_code(market, num, expected):
    assert to_code(market, num) == expected


def test_main(tmp_path):
    data = b"".join([
        DAY_LAYOUT.pack(20200102, 1234, 1300, 1200, 1250, 12500.0, 1000, 0),
        DAY_LAYOUT.pack(20261113, 1234, 1300, 1200, 1250, 25000.0, 2000, 0),
        DAY_LAYOUT.pack(20260230, 1234, 1300, 1200, 1250, 12500.0, 1000, 0),
    ])
    suspect = DAY_LAYOUT.pack(20261113, 1234, 1300, 1200, 1250, 1.0, 1000, 0)
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr(r"sh\lday\sh600000.day", data)
        archive.writestr("sz/lday/sz300750.day", suspect)
        archive.writestr(r"bj\lday\bj920000.day", b"")
    zip_path = tmp_path / "hsjday.zip"
    zip_path.write_bytes(buffer.getvalue())
    out = tmp_path / "out"
    assert main(["--zip", str(zip_path), "--codes",
                 "600000.SH,300750.SZ,920000.BJ,000001.SZ", "--out", str(out)]) == 0
    with (out / "tdx_day_sample.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == [
            "code", "trade_date", "open", "high", "low", "close", "volume", "amount"
        ]
        rows = list(reader)
    assert len(rows) == 3
    assert rows[0] == dict(code="600000.SH", trade_date="2020-01-02", open="12.34",
                           high="13", low="12", close="12.5", volume="1000", amount="12500.0000")
    assert rows[1]["trade_date"] == "2026-11-13"
    assert rows[1]["volume"] == "2000"
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["600000.SH"] == dict(
        rows=2, first="2020-01-02", last="2026-11-13", rejected={"invalid_date": 1},
        unit_suspect=False, sha256=hashlib.sha256(data).hexdigest(), missing=False,
    )
    assert summary["300750.SZ"]["unit_suspect"] is True
    assert summary["920000.BJ"]["missing"] is False
    assert summary["920000.BJ"]["rows"] == 0
    assert summary["000001.SZ"] == dict(
        rows=0, first=None, last=None, rejected={}, unit_suspect=False,
        sha256=None, missing=True,
    )
