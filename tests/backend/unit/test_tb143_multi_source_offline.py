"""T-B143 合成数据验收：不使用真实行情、真实密钥、网络或 PG。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import socket
import struct
import sys
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal
from pathlib import Path, PureWindowsPath
from types import ModuleType
from zipfile import ZipFile

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, MetaData, Table
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.schema import CreateTable

from app.cli import tb143_export
from app.db.base import NAMING_CONVENTION
from app.db.tables.market import ex_rights_events, minute_file_catalog
from app.ingest.gbbq import (
    GbbqRefused,
    decode_gbbq,
    load_pytdx_keys,
    read_gbbq_zip,
    ref_price,
)
from app.ingest.minute_catalog import (
    CatalogEntry,
    check_overlap,
    effective_range,
    hf_entries_from_manifest,
    resolve,
    validate_rel_path,
)
from app.ingest.tdx_history import DayRefusal, iter_day_zip
from app.ingest.tdx_local import DAY_LAYOUT, ParseResult

# 完全虚构的格式表，仅供往返构造；禁止替换为真实 pytdx 密钥。
_rng = random.Random(143)
KEYS = tuple(_rng.getrandbits(32) for _ in range(1042))
CODE = "600999.SH"
GENERATOR = "c" * 40


@pytest.fixture(autouse=True)
def no_socket(monkeypatch):
    """所有用例均阻止意外出网。"""

    def fail(*_args, **_kwargs):
        pytest.fail("离线验收不得出网")

    monkeypatch.setattr(socket.socket, "connect", fail)


def _encrypt_record(clear: bytes) -> bytes:
    """测试独立实现逆变换：从明文逐轮倒推密文，不依赖被测解码函数。"""
    result = bytearray()
    mask = 0xFFFFFFFF
    for offset in range(0, 24, 8):
        a, b = struct.unpack_from("<II", clear, offset)
        left, right = b, a ^ KEYS[0]
        for j in range(1, 17):
            old_left = right
            f = (KEYS[274 + ((old_left >> 16) & 255)] + KEYS[18 + (old_left >> 24)]) & mask
            f ^= KEYS[530 + ((old_left >> 8) & 255)]
            f = (f + KEYS[786 + (old_left & 255)]) & mask
            left, right = old_left, (left ^ f ^ KEYS[j]) & mask
        result.extend(struct.pack("<II", left ^ KEYS[17], right))
    result.extend(clear[24:])
    return bytes(result)


def _event(market=1, symbol=b"600999", day=20250102, category=1, values=(2.0, 8.0, 1.0, 1.0)):
    return _encrypt_record(struct.pack("<B7sIBffff", market, symbol, day, category, *values))


def _package(*events):
    return struct.pack("<I", len(events)) + b"".join(events)


def _day(day=20250102, amount=8638.0, price=1234):
    return DAY_LAYOUT.pack(day, price, price, price, price, amount, 700, 0)


def _zip_bytes(members):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _day_results(members, before=None, eligible=frozenset({CODE})):
    with ZipFile(io.BytesIO(_zip_bytes(members))) as archive:
        return list(iter_day_zip(archive, eligible, before))


def _manifest(**changes):
    row = dict(
        exchange="SH",
        symbol="600999",
        is_bj="False",
        universe_status="D",
        rows="240",
        days="1",
        first_ts="2026-08-06 09:31:00+08:00",
        last_ts="2026-08-06 15:00:00+08:00",
        sha256="a" * 64,
    )
    return row | changes


def _write_manifest(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_msi_day_volume_shares_not_multiplied():
    [(code, result)] = _day_results({r"sh\lday\sh600999.day": _day()})
    assert code == CODE and isinstance(result, ParseResult)
    [bar] = result.bars
    assert (bar.open, bar.volume, bar.amount) == (
        Decimal("12.34"),
        Decimal("700"),
        Decimal("8638.0000"),
    )


def test_msi_day_duplicate_date_rejects_file():
    results = _day_results(
        {
            "sh/lday/sh600999.day": _day() + _day(price=0),
            "sz/lday/sz000999.day": _day(),
        },
        eligible={CODE, "000999.SZ"},
    )
    assert results[0] == (CODE, DayRefusal("duplicate_date", file_refused=True))
    assert isinstance(results[1][1], ParseResult) and len(results[1][1].bars) == 1


def test_msi_day_no_until_cutoff():
    data = _day(day=20200102) + _day(day=20261113)
    [(_, all_rows)] = _day_results({"sh/lday/sh600999.day": data})
    [(_, filtered)] = _day_results({"sh/lday/sh600999.day": data}, before=date(2026, 11, 13))
    assert isinstance(all_rows, ParseResult) and len(all_rows.bars) == 2
    assert isinstance(filtered, ParseResult) and len(filtered.bars) == 1
    assert filtered.rejected["filtered_before"] == 1


def test_day_record_refusal_and_whole_file_unit_check():
    [(_, parsed)] = _day_results({"sh/lday/sh600999.day": _day() + _day(day=20260230)})
    assert isinstance(parsed, ParseResult)
    assert len(parsed.bars) == 1 and parsed.rejected == {"invalid_date": 1}
    [(_, suspect)] = _day_results(
        {
            "sh/lday/sh600999.day": _day() + _day(day=20261113, amount=1.0),
        },
        before=date(2026, 1, 1),
    )
    assert suspect == DayRefusal("unit_suspect", file_refused=True)
    [(_, truncated)] = _day_results({"sh/lday/sh600999.day": _day() + b"x"})
    assert truncated == DayRefusal("truncated_file", file_refused=True)


def test_day_market_directory_eligibility_and_bj():
    results = _day_results(
        {
            "sh/lday/sz000999.day": _day(),
            "sh/lday/sh600998.day": _day(),
            r"bj\lday\bj920999.day": _day(),
            "readme.txt": b"",
        },
        eligible={"920999.BJ"},
    )
    assert results[0][1] == DayRefusal("name_invalid")
    assert results[1] == ("600998.SH", DayRefusal("not_eligible"))
    assert results[2][0] == "920999.BJ" and isinstance(results[2][1], ParseResult)
    assert results[3][1] == DayRefusal("not_target_file")


def test_msi_gbbq_category1_shsz_only():
    events = decode_gbbq(
        _package(
            _event(),
            _event(market=0, symbol=b"000999"),
            _event(category=2),
            _event(market=2),
        ),
        KEYS,
    )
    assert [event.code for event in events] == [CODE, "000999.SZ"]
    assert asdict(events[0]) == dict(
        code=CODE,
        ex_date=date(2025, 1, 2),
        cash_per_share=Decimal("0.200000"),
        rights_price=Decimal("8.000000"),
        bonus_ratio=Decimal("0.100000"),
        rights_ratio=Decimal("0.100000"),
        source="tdx_gbbq",
    )
    assert all(
        value.as_tuple().exponent == -6
        for value in (
            events[0].cash_per_share,
            events[0].rights_price,
            events[0].bonus_ratio,
            events[0].rights_ratio,
        )
    )


def test_gbbq_quantizes_half_up():
    [event] = decode_gbbq(_package(_event(values=(0.15625, 0.0078125, 1.25, 2.5))), KEYS)
    assert event.cash_per_share == Decimal("0.015625")
    assert event.rights_price == Decimal("0.007813")
    assert event.bonus_ratio == Decimal("0.125000")
    assert event.rights_ratio == Decimal("0.250000")


@pytest.mark.parametrize("content", [b"", b"\0" * 3, struct.pack("<I", 1), _package(_event())[:-1]])
def test_gbbq_truncated_refuses_package(content):
    with pytest.raises(GbbqRefused, match="truncated_file"):
        decode_gbbq(content, KEYS)


def test_gbbq_invalid_date_and_duplicate_refuse_package():
    with pytest.raises(GbbqRefused, match="invalid_date"):
        decode_gbbq(_package(_event(), _event(day=20250230)), KEYS)
    with pytest.raises(GbbqRefused, match="duplicate_event"):
        decode_gbbq(_package(_event(), _event(values=(3.0, 9.0, 2.0, 2.0))), KEYS)
    assert decode_gbbq(_package(_event(day=20250230, category=2)), KEYS) == []


def test_gbbq_zip_sha_mismatch_refused(tmp_path):
    path = tmp_path / "gbbq.zip"
    path.write_bytes(_zip_bytes({"gbbq": _package(_event())}))
    with pytest.raises(GbbqRefused, match="sha256_mismatch"):
        read_gbbq_zip(path, "0" * 64, KEYS)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    snapshot, events = read_gbbq_zip(path, actual, KEYS)
    assert snapshot == actual and len(events) == 1


def test_load_pytdx_optional_and_fictitious_table(monkeypatch):
    monkeypatch.setitem(sys.modules, "pytdx.reader.gbbq_reader", None)
    with pytest.raises(GbbqRefused, match="pytdx_unavailable"):
        load_pytdx_keys()
    fake = ModuleType("pytdx.reader.gbbq_reader")
    fake.GbbqReader = type("GbbqReader", (), {"hexdump_keys": struct.pack("<1042I", *KEYS).hex()})
    monkeypatch.setitem(sys.modules, "pytdx.reader.gbbq_reader", fake)
    assert load_pytdx_keys() == KEYS


def test_msi_gbbq_ref_price():
    assert ref_price(*map(Decimal, ("12.00", "0.2", "8.00", "0.1", "0.1"))) == Decimal("10.50")


def test_msi_catalog_rel_path_and_root():
    rel = "hf/SH/600000.parquet"
    assert validate_rel_path(rel.replace("/", "\\")) == rel
    assert str(resolve(r"F:\data", rel)) == str(PureWindowsPath(r"F:\data\hf\SH\600000.parquet"))
    assert resolve("/mnt/f/data", rel) == Path("/mnt/f/data/hf/SH/600000.parquet")
    for bad in (
        "/absolute",
        "../escape",
        "a/../b",
        r"\absolute",
        "C:/drive",
        "C:drive",
        "a//b",
        "",
        "a/",
    ):
        with pytest.raises(ValueError, match="不安全"):
            validate_rel_path(bad)


def test_catalog_bj_empty_and_prefix_filter():
    rows = [
        _manifest(exchange="BJ", symbol="920999"),
        _manifest(is_bj="True"),
        _manifest(rows="0", first_ts="", last_ts=""),
        _manifest(symbol="900999"),
        _manifest(exchange="SZ", symbol="302999"),
        _manifest(),
    ]
    entries, counts = hf_entries_from_manifest(rows, GENERATOR)
    assert counts == {
        "skip_bj": 2,
        "skip_empty": 1,
        "reject_prefix": 1,
        "registered": 2,
    }
    assert [entry.code for entry in entries] == ["302999.SZ", CODE]
    assert asdict(entries[1]) == dict(
        source="hf_1min",
        code=CODE,
        kind="1m",
        date_from=date(2026, 8, 6),
        date_to=date(2026, 8, 6),
        rel_path="hf-1min/2022plus/SH/600999.parquet",
        sha256="a" * 64,
        row_count=240,
        splice_segment="hf_1m",
        generator=GENERATOR,
    )


def test_msi_catalog_one_source_per_stock_day():
    [hf], counts = hf_entries_from_manifest(
        [_manifest(last_ts="2026-08-07 15:00:00+08:00")], GENERATOR
    )
    lc = CatalogEntry(
        source="tdx_local",
        code=CODE,
        kind="1m",
        date_from=date(2026, 8, 7),
        date_to=date(2026, 8, 7),
        rel_path="tdx-min/600999.parquet",
        sha256="b" * 64,
        row_count=1,
        splice_segment="vipdoc_1m",
        generator=GENERATOR,
    )
    assert counts == {"registered": 1}
    assert hf.date_to == date(2026, 8, 7)
    assert effective_range(hf) == (date(2026, 8, 6), date(2026, 8, 6))
    assert effective_range(lc) == (date(2026, 8, 7), date(2026, 8, 7))
    check_overlap([hf], lc)
    check_overlap([hf, lc], lc)
    day = date(2026, 8, 7)
    assert [
        entry.source
        for entry in (hf, lc)
        if (interval := effective_range(entry)) and interval[0] <= day <= interval[1]
    ] == ["tdx_local"]
    with pytest.raises(ValueError, match="重叠"):
        check_overlap([hf, lc], replace(lc, rel_path="another.parquet"))
    with pytest.raises(ValueError, match="SHA256"):
        check_overlap([lc], replace(lc, sha256="c" * 64))
    check_overlap([lc], replace(lc, code="000999.SZ"))
    check_overlap([lc], replace(lc, kind="5m"))
    check_overlap([hf], replace(hf, rel_path="empty.parquet", date_from=day))
    assert effective_range(replace(hf, date_from=day)) is None
    assert effective_range(replace(lc, date_to=date(2026, 8, 6))) is None
    with pytest.raises(ValueError, match="未知"):
        effective_range(replace(lc, splice_segment="bad"))


def test_msi_minute_not_written_to_pg():
    probes = Path(__file__).resolve().parents[3] / "src/backend/probes"
    sql = "\n".join(
        (probes / name).read_text() for name in ("tb143_load_day.sql", "tb143_load_meta.sql")
    )
    sql = re.sub(r"--[^\n]*", "", sql)
    assert not re.search(
        r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:market\.)?minute(?:5)?_bars\b", sql, re.I
    )
    assert "INSERT INTO market.minute_file_catalog" in sql
    assert not re.search(r"\b(?:UPDATE|DELETE)\b", sql, re.I)


def test_catalog_malformed_fields_refused():
    entries, counts = hf_entries_from_manifest(
        [
            _manifest(first_ts="2026-08-06 09:31:00"),
            _manifest(first_ts="bad"),
            _manifest(sha256="bad"),
            _manifest(rows="-1"),
            _manifest(
                first_ts="2026-08-06 15:00:00+08:00",
                last_ts="2026-08-05 15:00:00+08:00",
            ),
        ],
        GENERATOR,
    )
    assert entries == [] and counts == {"reject_date": 2, "reject_catalog": 3}


def test_export_day_partial_and_summary(tmp_path):
    zip_path, eligible = tmp_path / "day.zip", tmp_path / "eligible.txt"
    zip_path.write_bytes(
        _zip_bytes(
            {
                r"sh\lday\sh600999.day": _day(day=20200102)
                + _day(day=20261113)
                + _day(day=20260230),
                "sz/lday/sz000999.day": _day(amount=1.0),
            }
        )
    )
    eligible.write_text(CODE + "\n000999.SZ\n", encoding="utf-8")
    out = tmp_path / "out"
    assert (
        tb143_export.main(
            [
                "day",
                "--zip",
                str(zip_path),
                "--eligible-codes",
                str(eligible),
                "--before",
                "2026-11-13",
                "--generator",
                GENERATOR,
                "--out",
                str(out),
            ]
        )
        == 1
    )
    with (out / "daily_bars.csv").open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows == [
        dict(
            code=CODE,
            trade_date="2020-01-02",
            adj_type="none",
            open="12.34",
            high="12.34",
            low="12.34",
            close="12.34",
            volume="700",
            amount="8638.0000",
        )
    ]
    summary = json.loads((out / "summary.json").read_text())["day"]
    assert summary["status"] == "partial" and summary["generator"] == GENERATOR
    assert summary["counts"] == {
        "files_parsed": 1,
        "record:invalid_date": 1,
        "record:filtered_before": 1,
        "rows_exported": 1,
        "file_refused:unit_suspect": 1,
    }
    assert summary["input_sha256"] == {
        "zip": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
        "eligible_codes": hashlib.sha256(eligible.read_bytes()).hexdigest(),
    }


def test_export_day_split_by_year(tmp_path):
    archive, eligible, out = tmp_path / "day.zip", tmp_path / "codes.txt", tmp_path / "out"
    archive.write_bytes(
        _zip_bytes({"sh/lday/sh600999.day": _day(day=20200102) + _day(day=20261113)})
    )
    eligible.write_text(CODE, encoding="utf-8")
    assert (
        tb143_export.main(
            [
                "day",
                "--zip",
                str(archive),
                "--eligible-codes",
                str(eligible),
                "--split-by-year",
                "--generator",
                GENERATOR,
                "--out",
                str(out),
            ]
        )
        == 0
    )
    summary = json.loads((out / "summary.json").read_text())["day"]
    assert set(summary["files"]) == {"day_2020.csv", "day_2026.csv"}
    for name, info in summary["files"].items():
        data = (out / name).read_bytes()
        assert info == {"rows": 1, "sha256": hashlib.sha256(data).hexdigest()}
        [row] = list(csv.DictReader(io.StringIO(data.decode())))
        assert row["trade_date"].startswith(name[4:8])
    assert not (out / "daily_bars.csv").exists()
    assert not list(out.glob("*.part"))


def test_msi_no_network(tmp_path, monkeypatch):
    from app.ingest import egress

    calls = []

    def fail(*args, **kwargs):
        calls.append((args, kwargs))
        pytest.fail("导出不应调用行情出口")

    monkeypatch.setattr(egress, "mairui_get", fail)
    monkeypatch.setattr(tb143_export, "load_pytdx_keys", lambda: KEYS)
    zip_path = tmp_path / "input.zip"
    zip_path.write_bytes(
        _zip_bytes(
            {
                "sh/lday/sh600999.day": _day(),
                "gbbq": _package(_event()),
            }
        )
    )
    eligible = tmp_path / "eligible.txt"
    eligible.write_text(CODE, encoding="utf-8")
    manifest = tmp_path / "manifest_files.csv"
    _write_manifest(manifest, [_manifest()])
    out = tmp_path / "out"
    common = ["--generator", GENERATOR, "--out", str(out)]
    assert (
        tb143_export.main(
            [
                "day",
                "--zip",
                str(zip_path),
                "--eligible-codes",
                str(eligible),
                *common,
            ]
        )
        == 0
    )
    assert (
        tb143_export.main(
            [
                "gbbq",
                "--zip",
                str(zip_path),
                "--expected-sha256",
                hashlib.sha256(zip_path.read_bytes()).hexdigest(),
                *common,
            ]
        )
        == 0
    )
    assert tb143_export.main(["hf-catalog", "--manifest-files-csv", str(manifest), *common]) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert set(summary) == {"day", "gbbq", "hf-catalog"}
    with (out / "ex_rights_events.csv").open(encoding="utf-8", newline="") as stream:
        [event] = list(csv.DictReader(stream))
    assert event["snapshot_sha256"] == hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert event["cash_per_share"] == "0.200000" and event["source"] == "tdx_gbbq"
    with (out / "minute_file_catalog.csv").open(encoding="utf-8", newline="") as stream:
        [entry] = list(csv.DictReader(stream))
    assert entry["generator"] == GENERATOR and entry["splice_segment"] == "hf_1m"
    assert not calls


def test_export_gbbq_refusal_has_no_partial_csv(tmp_path, monkeypatch):
    monkeypatch.setattr(tb143_export, "load_pytdx_keys", lambda: KEYS)
    archive = tmp_path / "gbbq.zip"
    archive.write_bytes(_zip_bytes({"gbbq": _package(_event(), _event(day=20250230))}))
    out = tmp_path / "out"
    assert (
        tb143_export.main(
            [
                "gbbq",
                "--zip",
                str(archive),
                "--expected-sha256",
                hashlib.sha256(archive.read_bytes()).hexdigest(),
                "--generator",
                GENERATOR,
                "--out",
                str(out),
            ]
        )
        == 2
    )
    assert not (out / "ex_rights_events.csv").exists()
    assert not list(out.glob("*.part"))
    assert json.loads((out / "summary.json").read_text())["gbbq"]["error"] == "invalid_date"


def _migration():
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(__file__).resolve().parents[3] / "src/backend/migrations"),
    )
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0038"]
    revision = script.get_revision("0036")
    assert revision.down_revision == "0035"
    return revision.module


def test_migration_matches_metadata(monkeypatch):
    migration = _migration()
    tables = []
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    def create(name, *columns, **kwargs):
        tables.append(Table(name, metadata, *columns, **kwargs))

    monkeypatch.setattr(migration.op, "create_table", create)
    migration.upgrade()
    for actual, expected in zip(tables, (ex_rights_events, minute_file_catalog), strict=True):
        assert str(CreateTable(actual).compile(dialect=dialect())) == str(
            CreateTable(expected).compile(dialect=dialect())
        )
        assert all(not column.nullable for column in actual.columns)
        assert all(c.name for c in actual.constraints if isinstance(c, CheckConstraint))


@pytest.mark.parametrize("counts", [(1, 0), (0, 1), (1, 1), (0, 0)])
def test_migration_downgrade_refuses_nonempty(monkeypatch, counts):
    migration = _migration()
    values = iter(counts)

    class Count:
        def scalar_one(self):
            return next(values)

    class Connection:
        def execute(self, _sql):
            return Count()

    dropped = []
    monkeypatch.setattr(migration.op, "get_bind", Connection)
    monkeypatch.setattr(migration.op, "drop_table", lambda name, **_: dropped.append(name))
    if any(counts):
        with pytest.raises(RuntimeError, match="非空"):
            migration.downgrade()
        assert dropped == []
    else:
        migration.downgrade()
        assert dropped == ["minute_file_catalog", "ex_rights_events"]


def test_migration_emits_postgres_ddl():
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer}
    )
    with Operations.context(context):
        _migration().upgrade()
    ddl = buffer.getvalue()
    assert "CREATE TABLE market.ex_rights_events" in ddl
    assert "CREATE TABLE market.minute_file_catalog" in ddl
    assert "create_hypertable" not in ddl
