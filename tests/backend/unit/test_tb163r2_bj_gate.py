from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app import bj_offline_volume as gate
from app.marketdata import daily_bars as writer
@pytest.fixture
def evidence(monkeypatch):
    monkeypatch.setattr(gate, "_bj_offline_volume_codes", frozenset())
    return [dict(mairui=dict(code=f"920{i:03}.BJ", t="2031-01-02 00:00:00", v="1"),
                 tdx_local=dict(code=f"920{i:03}.BJ", trade_date="20310102", volume=100, source="tdx_local")) for i in range(20)]
@pytest.mark.parametrize("side,patch,error", [
    *[(side, {field: value}, "requires_20") for side, field, values in [("mairui", "v", [0]), ("tdx_local", "volume", [0]), ("mairui", "sf", [1, "1", True, "true", "True"]), ("tdx_local", "is_suspended", [1, "1", True, "true", "True"])] for value in values],
    *[("mairui", {"v": value}, "field_invalid") for value in [1.0, True, None, "bad", "NaN", "Infinity"]],
    ("mairui", {"v": "1.000000000000000000000000000001"}, "volume_mismatch"), ("mairui", {"v": -1}, "volume_mismatch"), ("tdx_local", {"volume": -1}, "volume_mismatch"), ("tdx_local", {"volume": "100.1"}, "volume_mismatch"),
    *[("mairui", {"t": value}, error) for value, error in [("2031-01-02 00:00:01", "trade_date_invalid"), ("20310230", "trade_date_invalid"), ("2031-01-03", "date_mismatch")]],
    ("tdx_local", {"source": "fake"}, "source_invalid"), ("mairui", {"code": "920999.BJ"}, "code_mismatch"), *[("tdx_local", {"code": code}, "code_mismatch") for code in ["600000.BJ", "999999.BJ", "92000.BJ"]]])
def test_invalid_evidence_revokes(evidence, side, patch, error, bj_isolated_list):
    bj_isolated_list(["920000.BJ"])
    assert gate.confirm_bj_offline_volume_units(evidence) == frozenset(f"920{i:03}.BJ" for i in range(20))
    assert not gate._bj_write_unconfirmed({"code": "920000.BJ"})
    assert gate._bj_write_unconfirmed({"code": "920999.BJ"})
    for target in (("mairui", "tdx_local") if side == "tdx_local" and "code" in patch else (side,)): evidence[0][target].update(patch)
    with pytest.raises(gate.RowReject, match=error): gate.confirm_bj_offline_volume_units(evidence)
    assert gate._bj_write_unconfirmed({"code": "920000.BJ"})
@pytest.mark.parametrize("case", ["split", "duplicate", "nineteen", "empty", "pair", "mapping"])
def test_insufficient_or_malformed(evidence, case):
    rows = {"split": [dict(mairui=dict(p["mairui"], t=f"203101{i + 1:02}"), tdx_local=dict(p["tdx_local"], trade_date=f"203101{i + 1:02}")) for i, p in enumerate(evidence)], "duplicate": [evidence[0]] * 20, "nineteen": evidence[:19], "empty": [], "pair": [None], "mapping": [{}]}[case]
    with pytest.raises(gate.RowReject, match="requires_20|pair_invalid"): gate.confirm_bj_offline_volume_units(rows)
@pytest.mark.parametrize("confirmed", [False, True])
@pytest.mark.parametrize("isolated", [False, True])
def test_writer_gate(evidence, confirmed, isolated, bj_isolated_list):
    if isolated: bj_isolated_list(["920000.BJ"])
    allowed = confirmed and isolated
    if confirmed: assert len(gate.confirm_bj_offline_volume_units(evidence)) == 20
    bars = [writer.DailyBar(code, date(2031, 1, 2), "none", *([None] * 8)) for code in ["920000.BJ", "600000.SH", "000001.SZ"]]
    expected = ["000001.SZ", "600000.SH"] + (["920000.BJ"] if allowed else [])
    def execute(statement):
        codes = [v for k, v in statement.compile().params.items() if k.startswith("code_m")]
        assert codes == expected
        return SimpleNamespace(all=lambda: [SimpleNamespace(code=c, trade_date=bars[0].trade_date, adj_type="none") for c in codes])
    conn = Mock(execute=Mock(side_effect=execute))
    assert writer.upsert_daily_bars(conn, writer.FetchResult(bars), source="tdx_local", licence_id=None, fetched_at=datetime.now(timezone.utc)) == writer.UpsertStats(len(expected), 0, 0, () if allowed else ("blocked_bj_unconfirmed",), blocked_bj_unconfirmed=int(not allowed))
    for code in ["600000.BJ", "920999.SH", "920999", "920999.bj"]:
        with pytest.raises(ValueError, match="qualified_code_invalid"): writer.upsert_daily_bars(conn, writer.FetchResult([writer.DailyBar(code, date(2031, 1, 2), "none", *([None] * 8))]), source="tdx_local", licence_id=None, fetched_at=datetime.now(timezone.utc))
