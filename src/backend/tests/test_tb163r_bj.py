"""B2/B4/B5/B6 regression checks; synthetic rows and in-memory connections only."""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import bj_offline_volume as gate
from app.marketdata import daily_bars as writer
from probes import tb140_history_selfcheck as fixtures

ld, bf = fixtures.ld, fixtures.bf


def pairs():
    return [{"mairui": {"code": f"920{i:03}.BJ", "t": "2031-01-02 00:00:00", "v": "1"},
             "tdx_local": {"code": f"920{i:03}.BJ", "trade_date": "20310102",
                           "volume": 100, "source": "tdx_local"}} for i in range(20)]


@pytest.fixture(autouse=True)
def reset_confirmation():
    with pytest.raises(gate.RowReject):
        gate.confirm_bj_offline_volume_units([])
    yield
    with pytest.raises(gate.RowReject):
        gate.confirm_bj_offline_volume_units([])


@pytest.mark.parametrize("side,field,value", [
    ("mairui", "v", "0"), ("tdx_local", "volume", 0),
    *[(side, field, value) for side, field in (("mairui", "sf"), ("tdx_local", "is_suspended"))
      for value in (1, "1", True, "true")],
    ("mairui", "v", "1.000000000000000000000000000001"),
    ("mairui", "v", 1.0), ("tdx_local", "volume", 100.0),
    ("mairui", "t", "2031-01-02 00:01:00"),
    ("tdx_local", "source", "fake"), ("tdx_local", "code", "009998.BJ"),
])
def test_rejected_evidence_revokes_confirmation(side, field, value):
    assert ld.confirm_bj_offline_volume_units is gate.confirm_bj_offline_volume_units
    assert ld.RowReject is gate.RowReject
    ld.confirm_bj_offline_volume_units(pairs())
    assert not ld._bj_write_unconfirmed({"code": "920999.BJ"})
    evidence = pairs()
    evidence[0][side][field] = value
    with pytest.raises(ld.RowReject):
        ld.confirm_bj_offline_volume_units(evidence)
    assert ld._bj_write_unconfirmed({"code": "920999.BJ"})


@pytest.mark.parametrize("case", ["cross_day", "duplicate", "nineteen"])
def test_common_day_and_distinct_codes(case):
    evidence = pairs()
    if case == "cross_day":
        for i, pair in enumerate(evidence):
            pair["mairui"]["t"] = pair["tdx_local"]["trade_date"] = f"2031-01-{i + 1:02}"
    else:
        evidence = [evidence[0]] * 20 if case == "duplicate" else evidence[:19]
    with pytest.raises(ld.RowReject):
        ld.confirm_bj_offline_volume_units(evidence)


def test_exclusions_leave_twenty_valid_codes():
    evidence = pairs()
    excluded = pairs()[0]
    excluded["mairui"]["code"] = excluded["tdx_local"]["code"] = "920900.BJ"
    excluded["mairui"].update(v="0", sf="1")
    evidence[0]["mairui"]["v"] = "1.000000000000000000000000000000"
    assert len(ld.confirm_bj_offline_volume_units([excluded, *evidence])) == 20


@pytest.mark.parametrize("text", ["2031-01-02", "20310102", "2031-01-02 00:00:00"])
def test_date_normalization(text):
    assert ld.validate_bar(fixtures._bar(t=text), "920999.BJ")["trade_date"] == "2031-01-02"
    with pytest.raises(ld.RowReject, match="trade_date_invalid"):
        ld.validate_bar(fixtures._bar(t="2031-01-02 00:00:01"), "920999.BJ")


@pytest.mark.parametrize("source", ["tdx_local", "mairui", "fake"])
def test_public_writer_filters_before_insert(source):
    def execute(statement):
        params = statement.compile().params
        codes = [value for key, value in params.items() if key.startswith("code_m")]
        assert codes == expected
        return SimpleNamespace(all=lambda: [SimpleNamespace(
            code=code, trade_date=date(2031, 1, 2), adj_type="none") for code in codes])

    conn = Mock(execute=Mock(side_effect=execute))
    result = writer.FakeDailyBarsSource().fetch(
        ["920999.BJ", "600997.SH", "000997.SZ"], date(2031, 1, 2), date(2031, 1, 2), "none")
    for confirmed in (False, True, False):
        if confirmed:
            ld.confirm_bj_offline_volume_units(pairs())
        else:
            with pytest.raises(ld.RowReject):
                ld.confirm_bj_offline_volume_units([])
        expected = ["000997.SZ", "600997.SH"] + (["920999.BJ"] if confirmed else [])
        stats = writer.upsert_daily_bars(conn, result, source=source, licence_id=None,
                                        fetched_at=datetime.now(timezone.utc))
        assert stats.inserted == len(expected)
        assert stats.blocked_bj_unconfirmed == (0 if confirmed else 1)


def test_backfill_blocked_bj_remains_pending(tmp_path):
    ws = fixtures._workspace(tmp_path)
    ws["codes"].write_text("600997\n920999\n")
    db = fixtures.FakePg()

    def persist(rows):
        assert "920999" not in bf.load_counter(ws["counter"])["done_history"]
        return ld.apply_daily_bars(db, rows, None)

    for confirmed in (False, True):
        if confirmed:
            ld.confirm_bj_offline_volume_units(pairs())
        summary = bf.run_batch(
            codes_file=ws["codes"], licence_file=None, secret="SYNTHETIC",
            counter_path=ws["counter"], stop_path=ws["stop"], run_dir=ws["run"],
            connection_factory=lambda: fixtures.ScriptedConn([(200, [fixtures._bar()])] * 2),
            sleeper=lambda _: None, persist_rows=persist)
        state = bf.load_counter(ws["counter"])
        assert summary["done"] == 1 and not state["halted"]
        assert summary["remaining"] == (0 if confirmed else 1)
        assert summary["blocked_bj_unconfirmed"] == ([] if confirmed else ["920999"])
        assert ("920999" in state["done_history"]) == confirmed
        assert ("920999" in state["history_windows"]) == confirmed
        assert "600997" in state["done_history"]
        assert state["total"] == (3 if confirmed else 2)
        assert len(db.table) == (2 if confirmed else 1)
