"""T-B213 realtime collection gates and response handling; synthetic and offline."""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.marketdata import realtime_collect
from app.workers import jobs

OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
LICENCE = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
NOW = dt.datetime(2030, 6, 11, 2, 0, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def _live_mode_for_collection_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIRUI_MODE", "live")


class _Context:
    def __init__(self, value: object, on_exit: object | None = None) -> None:
        self.value = value
        self.on_exit = on_exit

    def __enter__(self) -> object:
        return self.value

    def __exit__(self, *_args: object) -> bool:
        if callable(self.on_exit):
            self.on_exit()
        return False


class _Engine:
    def __init__(self) -> None:
        self.connection = Mock()
        self.write_open = False
        self.begin_calls = 0

    def connect(self) -> _Context:
        return _Context(self.connection)

    def begin(self) -> _Context:
        self.begin_calls += 1
        self.write_open = True
        return _Context(self.connection, lambda: setattr(self, "write_open", False))


def test_default_switch_is_off_and_does_not_create_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(realtime_quotes_source="off")
    denied = Mock(side_effect=AssertionError("off switch must return before engine creation"))
    monkeypatch.setattr(jobs, "_engine", denied)
    assert realtime_collect.realtime_quotes_task(settings) == 0
    denied.assert_not_called()


def test_replay_mode_skips_engine_licence_and_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIRUI_MODE", "replay")
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    engine = Mock(side_effect=AssertionError("replay mode must return before engine creation"))
    licence = Mock(side_effect=AssertionError("replay mode must not read a licence"))
    secret = Mock(side_effect=AssertionError("replay mode must not read credentials"))
    lease = Mock(side_effect=AssertionError("replay mode must not open egress"))
    client = Mock(side_effect=AssertionError("replay mode must not call mairui"))
    monkeypatch.setattr(jobs, "_engine", engine)
    monkeypatch.setattr(realtime_collect, "active_licence_id", licence)
    monkeypatch.setattr(realtime_collect, "credential", secret)
    monkeypatch.setattr(realtime_collect, "single_egress", lease)
    monkeypatch.setattr(realtime_collect, "mairui_get", client)

    assert realtime_collect.realtime_quotes_task(settings, now=NOW) == 0
    engine.assert_not_called()
    licence.assert_not_called()
    secret.assert_not_called()
    lease.assert_not_called()
    client.assert_not_called()


def test_task_reuses_supplied_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    engine = _Engine()
    clock = SimpleNamespace(trade_date=NOW.date(), session=SimpleNamespace(value="morning"))
    monkeypatch.setattr(realtime_collect, "_approved_owners", lambda _conn: [OWNER])
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: clock)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])
    monkeypatch.setattr(
        realtime_collect,
        "_fetch_with_egress",
        lambda *_args, **_kwargs: (200, [{"code": "600000.SH", "ts": NOW}]),
    )
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: 1)
    engine_factory = Mock(side_effect=AssertionError("supplied engine must be reused"))
    monkeypatch.setattr(jobs, "_engine", engine_factory)

    assert realtime_collect.realtime_quotes_task(settings, owner=OWNER, now=NOW, engine=engine) == 1
    engine_factory.assert_not_called()


@pytest.mark.parametrize("flag", ["stop", "halt"])
def test_stop_and_halt_gates_precede_credential_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flag: str
) -> None:
    stop = tmp_path / "STOP"
    halt = tmp_path / "HALT"
    (stop if flag == "stop" else halt).write_text("", encoding="utf-8")
    secret_loader = Mock(side_effect=AssertionError("gate must precede credential load"))
    monkeypatch.setattr(realtime_collect, "get_ingest_core", Mock())

    with pytest.raises(
        realtime_collect.RealtimeCollectionStoppedError, match="STOP_or_halt_present"
    ):
        realtime_collect._fetch_with_egress(
            Mock(),
            SimpleNamespace(),
            owner=OWNER,
            licence_id=LICENCE,
            now=NOW,
            path="/synthetic",
            upstream=None,
            secret_loader=secret_loader,
            stop=stop,
            halt=halt,
        )
    secret_loader.assert_not_called()


def test_missing_core_fails_closed_before_credential_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(realtime_collect, "get_ingest_core", lambda: None)
    secret_loader = Mock(side_effect=AssertionError("credential must not load without core"))
    with pytest.raises(
        realtime_collect.RealtimeCollectionStoppedError, match="ingest_core_unavailable"
    ):
        realtime_collect._fetch_with_egress(
            Mock(),
            SimpleNamespace(),
            owner=OWNER,
            licence_id=LICENCE,
            now=NOW,
            path="/synthetic",
            upstream=None,
            secret_loader=secret_loader,
            stop=tmp_path / "STOP",
            halt=tmp_path / "HALT",
        )
    secret_loader.assert_not_called()


def test_config_switch_defaults_off() -> None:
    assert realtime_collect.Settings.model_fields["realtime_quotes_source"].default == "off"


def test_worker_does_not_register_realtime_task() -> None:
    settings = SimpleNamespace(
        business=SimpleNamespace(
            realtime=SimpleNamespace(intervals=SimpleNamespace(quote_interval_s=17))
        ),
        cooldown_purge_interval_s=60,
        import_rows_purge_interval_s=60,
        import_raw_purge_interval_s=60,
    )
    assert "market.realtime_quotes_fetch" not in jobs.schedule(settings)
    assert "market.realtime_quotes_fetch" not in jobs.TASKS
    assert "market.realtime_quotes_fetch" not in jobs.LOCKED_TASKS


@pytest.mark.parametrize("status", [101, 103, 429, 503, 500])
def test_upstream_status_stops_before_normalization(status: int) -> None:
    with pytest.raises(realtime_collect.RealtimeCollectionStoppedError):
        realtime_collect._validate_response(status, [])


def test_json_error_stops_before_normalization() -> None:
    with pytest.raises(realtime_collect.RealtimeCollectionStoppedError):
        realtime_collect._validate_response(200, {"error": "synthetic"})


def test_malformed_json_stops_before_normalization() -> None:
    with pytest.raises(realtime_collect.RealtimeCollectionStoppedError):
        realtime_collect._validate_response(200, "not-json")


@pytest.mark.parametrize(
    "value",
    [dt.datetime(2030, 6, 11, 10, 0), 1_813_000_000],
)
def test_timestamp_requires_explicit_timezone(value: object) -> None:
    with pytest.raises(realtime_collect.RealtimeCollectionStoppedError, match="timestamp_invalid"):
        realtime_collect._quote_timestamp(value)


def test_credential_echo_is_rejected_before_normalization() -> None:
    with pytest.raises(
        realtime_collect.RealtimeCollectionStoppedError, match="credential_echo_rejected"
    ):
        realtime_collect._reject_credential_echo("synthetic-secret", {"data": "synthetic-secret"})


def test_content_fingerprint_ignores_fetch_time() -> None:
    row = {"price": "12.34", "payload": {"code": "600000.SH"}, "fetched_at": NOW}
    later = {**row, "fetched_at": NOW + dt.timedelta(seconds=30)}
    assert realtime_collect._fingerprint(row) == realtime_collect._fingerprint(later)


def test_normalization_preserves_snapshot_fields_and_timestamp() -> None:
    rows = realtime_collect._normalise_rows(
        ["600000.SH"],
        [
            {
                "code": "600000.SH",
                "ts": "2030-06-11T10:00:00+08:00",
                "price": "12.34",
                "pct_change": "1.2",
                "volume": "100",
                "amount": "1234",
            }
        ],
        NOW,
    )
    assert rows[0]["source"] == "mairui"
    assert rows[0]["ts"] == dt.datetime(2030, 6, 11, 2, tzinfo=dt.UTC)
    assert rows[0]["volume"] == "100"
    assert rows[0]["is_suspended"] is None
    assert rows[0]["limit_up"] is None
    assert rows[0]["limit_down"] is None


def test_normalization_maps_dm_code_from_ssjy_more_response() -> None:
    rows = realtime_collect._normalise_rows(
        ["600000.SH"],
        [{"dm": "600000.SH", "ts": "2030-06-11T10:00:00+08:00"}],
        NOW,
    )
    assert rows[0]["code"] == "600000.SH"


@pytest.mark.parametrize(
    "row",
    [{"ts": "2030-06-11T10:00:00+08:00"}, {"dm": "600001.SH", "ts": NOW}],
)
def test_normalization_rejects_missing_or_out_of_range_code(
    row: dict[str, object],
) -> None:
    with pytest.raises(realtime_collect.RealtimeCollectionStoppedError, match="code"):
        realtime_collect._normalise_rows(["600000.SH"], [row], NOW)


def test_nonmapped_response_keys_do_not_populate_snapshot_fields() -> None:
    rows = realtime_collect._normalise_rows(
        ["600000.SH"],
        [
            {
                "code": "600000.SH",
                "ts": NOW,
                "p": "99.99",
                "z": "99",
                "v": "999",
                "a": "9999",
                "e": "9999",
                "s": True,
                "u": True,
                "d": True,
            }
        ],
        NOW,
    )
    assert rows[0]["price"] is None
    assert rows[0]["pct_change"] is None
    assert rows[0]["volume"] is None
    assert rows[0]["amount"] is None
    assert rows[0]["is_suspended"] is None
    assert rows[0]["limit_up"] is None
    assert rows[0]["limit_down"] is None


def test_missing_quote_timestamp_stops_before_any_write(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    engine = _Engine()
    clock = SimpleNamespace(
        trade_date=NOW.astimezone(dt.timezone(dt.timedelta(hours=8))).date(),
        session=SimpleNamespace(value="morning"),
    )
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: clock)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])
    monkeypatch.setattr(
        realtime_collect,
        "_fetch_with_egress",
        lambda *_args, **_kwargs: (200, [{"code": "600000.SH", "price": "12.34"}]),
    )
    writes: list[object] = []
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: writes.append(True) or 1)

    with pytest.raises(
        realtime_collect.RealtimeCollectionStoppedError, match="realtime_timestamp_missing"
    ):
        realtime_collect.collect_realtime_quotes(
            engine.connection,
            settings,
            owner=OWNER,
            now=NOW,
            engine=engine,
        )
    assert writes == []
    assert engine.begin_calls == 0


@pytest.mark.parametrize("flag", ["stop", "halt"])
def test_stop_and_halt_after_response_prevent_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, flag: str
) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    engine = _Engine()
    clock = SimpleNamespace(
        trade_date=NOW.astimezone(dt.timezone(dt.timedelta(hours=8))).date(),
        session=SimpleNamespace(value="morning"),
    )
    stop = tmp_path / "STOP"
    halt = tmp_path / "HALT"
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: clock)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])

    def fetch(*_args: object, **_kwargs: object) -> tuple[int, object]:
        (stop if flag == "stop" else halt).write_text("", encoding="utf-8")
        return 200, [{"code": "600000.SH", "ts": NOW}]

    monkeypatch.setattr(realtime_collect, "_fetch_with_egress", fetch)
    writes: list[object] = []
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: writes.append(True) or 1)

    with pytest.raises(
        realtime_collect.RealtimeCollectionStoppedError, match="STOP_or_halt_present"
    ):
        realtime_collect.collect_realtime_quotes(
            engine.connection,
            settings,
            owner=OWNER,
            now=NOW,
            engine=engine,
            stop=stop,
            halt=halt,
        )
    assert writes == []
    assert engine.begin_calls == 0


def test_normalization_rejects_partial_batch() -> None:
    with pytest.raises(realtime_collect.RealtimeCollectionStoppedError, match="missing"):
        realtime_collect._normalise_rows(
            ["600000.SH", "000001.SZ"], [{"code": "600000.SH", "ts": NOW}], NOW
        )


def test_calendar_gate_returns_without_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = Mock()
    settings = SimpleNamespace(
        realtime_quotes_source="mairui", business=SimpleNamespace(market_rules=object())
    )
    monkeypatch.setattr(
        realtime_collect,
        "_open_clock",
        lambda *_args: None,
    )
    transport = Mock(side_effect=AssertionError("calendar gate must precede transport"))
    assert (
        realtime_collect.collect_realtime_quotes(
            conn,
            settings,
            owner=OWNER,
            now=NOW,
            upstream=transport,
            engine=Mock(),
        )
        == 0
    )
    transport.assert_not_called()


def test_owned_codes_include_etf_holdings_and_watchlist_but_exclude_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    watchlist_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: ["510050.SH", "000001.SH"])
    )
    securities_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: ["159919.SZ", "510050.SH"])
    )
    conn = Mock()
    conn.execute.side_effect = [watchlist_result, securities_result]
    monkeypatch.setattr(realtime_collect, "select_account", lambda *_args: OWNER)
    monkeypatch.setattr(
        realtime_collect,
        "_account",
        lambda *_args: SimpleNamespace(positions={"159919.SZ": object(), "399001.SZ": object()}),
    )

    assert realtime_collect._owned_codes(conn, OWNER, NOW.date()) == ["159919.SZ", "510050.SH"]
    sql = str(
        conn.execute.call_args_list[1].args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "'etf'" in sql and "'stock'" in sql
    assert "'index'" not in sql


def test_revision_allocation_uses_transaction_lock() -> None:
    row = {
        "code": "600000.SH",
        "ts": NOW,
        "source": "mairui",
        "source_licence_id": LICENCE,
    }
    conn = Mock()
    realtime_collect._lock_revision_keys(conn, [row])
    statement = str(conn.execute.call_args.args[0])
    assert "pg_advisory_xact_lock" in statement


def test_revision_fingerprint_reuse_and_content_change() -> None:
    base = {
        "code": "600000.SH",
        "ts": NOW,
        "source": "mairui",
        "source_licence_id": LICENCE,
        "price": "10.00",
        "pct_change": "1.00",
        "volume": "100",
        "amount": "1000",
        "payload": {"code": "600000.SH", "price": "10.00"},
        "is_suspended": None,
        "limit_up": None,
        "limit_down": None,
    }
    existing = [
        {
            "code": base["code"],
            "ts": base["ts"],
            "source_licence_id": base["source_licence_id"],
            "revision": 4,
            "content_fingerprint": realtime_collect._fingerprint(base),
        }
    ]
    changed = {**base, "price": "10.10", "payload": {"code": "600000.SH", "price": "10.10"}}
    conn = Mock()
    conn.execute.side_effect = [
        SimpleNamespace(mappings=lambda: existing),
        SimpleNamespace(rowcount=1),
    ]
    lock = Mock()
    original_lock = realtime_collect._lock_revision_keys
    realtime_collect._lock_revision_keys = lock
    try:
        assert realtime_collect._write_rows(conn, [base, changed], uuid.uuid4()) == 1
    finally:
        realtime_collect._lock_revision_keys = original_lock

    lock.assert_called_once()
    statement = conn.execute.call_args_list[-1].args[0]
    values = statement._multi_values[0]
    assert [value["revision"] for value in values] == [4, 5]
    assert values[0]["content_fingerprint"] == realtime_collect._fingerprint(base)
    assert values[1]["content_fingerprint"] == realtime_collect._fingerprint(changed)


def test_each_batch_refreshes_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    fake_engine = _Engine()
    open_clock = SimpleNamespace(
        trade_date=NOW.astimezone(dt.timezone(dt.timedelta(hours=8))).date(),
        session=SimpleNamespace(value="morning"),
    )
    stamps = [NOW, NOW + dt.timedelta(seconds=1), NOW + dt.timedelta(seconds=2)]
    seen: list[dt.datetime] = []
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: open_clock)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(
        realtime_collect,
        "_owned_codes",
        lambda *_args: [f"600{i:03d}.SH" for i in range(21)],
    )

    def fetch(*_args: object, **kwargs: object) -> tuple[int, object]:
        seen.append(kwargs["now"])  # type: ignore[arg-type]
        codes = str(kwargs["path"]).split("=")[-1].split(",")
        return 200, [{"code": code, "ts": NOW} for code in codes]

    monkeypatch.setattr(realtime_collect, "_fetch_with_egress", fetch)
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: 1)
    assert (
        realtime_collect.collect_realtime_quotes(
            fake_engine.connection,
            settings,
            owner=OWNER,
            clock=iter(stamps).__next__,
            engine=fake_engine,
        )
        == 1
    )
    assert seen == stamps[1:]


def test_closed_session_stops_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    closed = SimpleNamespace(
        trade_date=NOW.date(),
        session=SimpleNamespace(value="closed"),
    )
    transport = Mock(side_effect=AssertionError("closed session must not fetch"))
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: closed)
    assert (
        realtime_collect.collect_realtime_quotes(
            Mock(), settings, owner=OWNER, now=NOW, upstream=transport, engine=Mock()
        )
        == 0
    )
    transport.assert_not_called()


def test_missing_active_licence_stops_before_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    open_clock = SimpleNamespace(
        trade_date=NOW.date(),
        session=SimpleNamespace(value="morning"),
    )
    transport = Mock(side_effect=AssertionError("missing licence must not fetch"))
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: open_clock)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: None)
    assert (
        realtime_collect.collect_realtime_quotes(
            Mock(), settings, owner=OWNER, now=NOW, upstream=transport, engine=Mock()
        )
        == 0
    )
    transport.assert_not_called()


def test_response_batch_has_single_batch_id_at_write_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    fake_engine = _Engine()
    clock = SimpleNamespace(
        trade_date=NOW.astimezone(dt.timezone(dt.timedelta(hours=8))).date(),
        session=SimpleNamespace(value="morning"),
    )
    engine_factory = Mock(side_effect=AssertionError("injected engine must be reused"))
    monkeypatch.setattr(jobs, "_engine", engine_factory)
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: clock)
    monkeypatch.setattr(realtime_collect, "_approved_owners", lambda _conn: [OWNER])
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])
    monkeypatch.setattr(
        realtime_collect,
        "_fetch_with_egress",
        lambda *_args, **_kwargs: (200, [{"code": "600000.SH", "ts": NOW}]),
    )
    seen: list[uuid.UUID] = []
    monkeypatch.setattr(
        realtime_collect,
        "_write_rows",
        lambda _conn, rows, batch_id: seen.append(batch_id) or len(rows),
    )
    assert realtime_collect.realtime_quotes_task(settings, now=NOW, engine=fake_engine) == 1
    engine_factory.assert_not_called()
    assert len(seen) == 1
    assert isinstance(seen[0], uuid.UUID)


def test_first_owner_rate_limit_stops_before_second_owner(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    fake_engine = _Engine()
    owner_two = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2")
    clock = SimpleNamespace(
        trade_date=NOW.astimezone(dt.timezone(dt.timedelta(hours=8))).date(),
        session=SimpleNamespace(value="morning"),
    )
    calls: list[uuid.UUID] = []
    monkeypatch.setattr(jobs, "_engine", lambda _settings: fake_engine)
    monkeypatch.setattr(realtime_collect, "_approved_owners", lambda _conn: [OWNER, owner_two])
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: clock)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])

    def fetch(*_args: object, **kwargs: object) -> tuple[int, object]:
        calls.append(kwargs["owner"])  # type: ignore[arg-type]
        return 429, []

    monkeypatch.setattr(realtime_collect, "_fetch_with_egress", fetch)
    with pytest.raises(realtime_collect.RealtimeCollectionStoppedError, match="http_429"):
        realtime_collect.realtime_quotes_task(settings, now=NOW, engine=fake_engine)
    assert calls == [OWNER]


def test_http_fetch_runs_before_write_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    fake_engine = _Engine()
    clock = SimpleNamespace(
        trade_date=NOW.astimezone(dt.timezone(dt.timedelta(hours=8))).date(),
        session=SimpleNamespace(value="morning"),
    )
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: clock)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])
    fetch_states: list[bool] = []

    def fetch(*_args: object, **_kwargs: object) -> tuple[int, object]:
        fetch_states.append(fake_engine.write_open)
        return 200, [{"code": "600000.SH", "ts": NOW}]

    monkeypatch.setattr(realtime_collect, "_fetch_with_egress", fetch)
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: 1)
    assert (
        realtime_collect.collect_realtime_quotes(
            fake_engine.connection,
            settings,
            owner=OWNER,
            now=NOW,
            engine=fake_engine,
        )
        == 1
    )
    assert fetch_states == [False]
    assert fake_engine.begin_calls == 1
