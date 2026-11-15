"""Synthetic TDX import CLI and dependency-adapter coverage; no real resources."""

from __future__ import annotations

import argparse
import datetime as dt
import socket
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from app.cli import daily_bars_backfill, tdx_import
from app.cli.tdx_import import DbDeps
from app.config import Settings
from app.ingest.tdx_local import (
    BEIJING,
    ExistingBar,
    Kind,
    RunReport,
    TdxBar,
    TdxRefused,
)
from app.marketdata import daily_bars as daily_bars_mod
from sqlalchemy.engine import Connection

NOW = dt.datetime(2026, 11, 10, 20, 0, tzinfo=BEIJING)
TODAY = NOW.date()
UNTIL = dt.date(2023, 11, 9)
DAY = dt.date(2023, 11, 6)
TS = dt.datetime(2023, 11, 6, 9, 31, tzinfo=BEIJING)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        pytest.fail("TDX import test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def make_bar(*, ts: dt.datetime | None = None, day: dt.date = DAY) -> TdxBar:
    return TdxBar(
        code="600000.SH",
        trade_date=day,
        ts=ts,
        open=Decimal(10),
        high=Decimal("10.2"),
        low=Decimal("9.8"),
        close=Decimal("10.1"),
        volume=Decimal(1000),
        amount=Decimal(10100),
    )


class FakeResult:
    def __init__(
        self,
        *,
        scalar: object = None,
        rows: Sequence[object] = (),
        scalar_rows: Sequence[object] = (),
    ) -> None:
        self.scalar = scalar
        self.rows = list(rows)
        self.scalar_rows = list(scalar_rows)

    def scalar_one_or_none(self) -> object:
        return self.scalar

    def all(self) -> list[object]:
        return list(self.rows)

    def scalars(self) -> FakeResult:
        return self

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.scalar_rows)


class FakeConnection:
    def __init__(self, results: Sequence[FakeResult] = ()) -> None:
        self.results = list(results)
        self.calls: list[object] = []
        self.rollbacks = 0

    def execute(self, statement: object) -> FakeResult:
        self.calls.append(statement)
        return self.results.pop(0) if self.results else FakeResult()

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeDeps:
    def __init__(self) -> None:
        self.open_days = {UNTIL}
        self.unknown_calendar = False
        self.recommended: dt.date | None = UNTIL
        self.previous: dict[dt.date, dt.date | None] = {}
        self.first: dict[str, dt.date] = {}
        self.owned = frozenset({"600000.SH"})
        self.written: list[tuple[Kind, Sequence[TdxBar], dt.datetime]] = []
        self.runs: list[tuple[RunReport, dt.date]] = []

    def is_open(self, day: dt.date) -> bool | None:
        return None if self.unknown_calendar else day in self.open_days

    def previous_open(self, day: dt.date) -> dt.date | None:
        return self.previous.get(day, day - dt.timedelta(days=1))

    def recommended_daily_until(self, now_bj: dt.datetime) -> dt.date | None:
        return self.recommended

    def first_mairui_minute_day(self, code: str) -> dt.date | None:
        return self.first.get(code)

    def normalize(self, raw: str) -> str:
        return raw

    def security_of(self, code: str) -> tuple[str, str | None] | None:
        return ("stock", "listed")

    def owned_codes(self, now_bj: dt.datetime) -> frozenset[str]:
        return self.owned

    def existing(
        self, kind: Kind, code: str, bars: Sequence[TdxBar]
    ) -> Mapping[object, ExistingBar]:
        return {}

    def write(self, kind: Kind, bars: Sequence[TdxBar], fetched_at: dt.datetime) -> int:
        self.written.append((kind, bars, fetched_at))
        return len(bars)

    def record_run(self, report: RunReport, run_date: dt.date) -> None:
        self.runs.append((report, run_date))


def daily_args() -> argparse.Namespace:
    return tdx_import._parser("daily-test", intraday=False).parse_args(
        [
            "--root",
            "synthetic-root",
            "--audit-dir",
            "synthetic-audit",
            "--until",
            UNTIL.isoformat(),
        ]
    )


def intraday_args() -> argparse.Namespace:
    return tdx_import._parser("intraday-test", intraday=True).parse_args(
        [
            "--root",
            "synthetic-root",
            "--audit-dir",
            "synthetic-audit",
            "--kind",
            "lc1",
            "--scope",
            "owned,exclude-bj",
            "--until",
            "2023-11-08",
        ]
    )


def capture_report(kwargs: Mapping[str, object], *, inserted: int = 0) -> RunReport:
    return RunReport(
        kind=str(kwargs["kind"]),
        run_id=str(kwargs["run_id"]),
        apply=kwargs["writer"] is not None,
        files=1,
        inserted=inserted,
    )


def test_year_window_and_recommended_until_boundaries() -> None:
    assert tdx_import._years_back(dt.date(2026, 11, 10), 3) == dt.date(2023, 11, 10)
    assert tdx_import._years_back(dt.date(2028, 2, 29), 3) == dt.date(2025, 2, 28)
    trade_date = dt.date(2026, 11, 10)
    days = [dt.date(2023, 11, 9), dt.date(2023, 11, 10), dt.date(2023, 11, 13)]
    assert tdx_import.recommended_until(trade_date, days) == dt.date(2023, 11, 10)
    assert tdx_import.recommended_until(trade_date, days[0:1] + days[2:]) == dt.date(
        2023, 11, 9
    )
    assert tdx_import.recommended_until(trade_date, [dt.date(2023, 11, 9)]) is None
    assert tdx_import.recommended_until(trade_date, [dt.date(2023, 11, 13)]) is None


def test_scope_iso_and_past_open_validation() -> None:
    assert tdx_import._scope("owned") == ("owned", frozenset())
    assert tdx_import._scope("owned,exclude-bj") == ("owned", frozenset({"bj"}))
    assert tdx_import._scope("market") == ("market", frozenset())
    for raw in ("", "other", "owned,exclude-bj,extra"):
        with pytest.raises(argparse.ArgumentTypeError):
            tdx_import._scope(raw)
    assert tdx_import._iso(None, "from") is None
    assert tdx_import._iso("2023-11-09", "from") == UNTIL
    with pytest.raises(TdxRefused, match="from_invalid"):
        tdx_import._iso("bad", "from")
    deps = FakeDeps()
    tdx_import._past_open(deps, UNTIL, TODAY, "until")
    for day in (TODAY, DAY):
        with pytest.raises(TdxRefused, match="until_must_be_past_open_day"):
            tdx_import._past_open(deps, day, TODAY, "until")
    deps.unknown_calendar = True
    with pytest.raises(TdxRefused, match="until_must_be_past_open_day"):
        tdx_import._past_open(deps, UNTIL, TODAY, "until")


def test_daily_execute_dry_run_captures_safe_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, object] = {}

    def fake_import(**kwargs: object) -> RunReport:
        captured.update(kwargs)
        return capture_report(kwargs)

    monkeypatch.setattr(tdx_import, "run_import", fake_import)
    deps = FakeDeps()
    code = tdx_import._execute(
        daily_args(), intraday=False, now=NOW, deps=deps, run_id="daily-fixed"
    )
    assert code == 0
    assert captured["kind"] == "day"
    assert captured["writer"] is None
    assert captured["compare_amount"] is True
    assert captured["scope_codes"] == deps.owned
    until_for = cast(Callable[[str], dt.date | None], captured["until_for"])
    assert until_for("600000.SH") == UNTIL
    assert deps.runs == []
    out = capsys.readouterr().out
    assert "recommended_until=2023-11-09" in out
    assert out.splitlines()[-1] == "dry-run"


def test_daily_execute_apply_writes_and_records_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, object] = {}

    def fake_import(**kwargs: object) -> RunReport:
        captured.update(kwargs)
        writer = cast(Callable[[Sequence[TdxBar]], int], kwargs["writer"])
        inserted = writer([make_bar()])
        return capture_report(kwargs, inserted=inserted)

    monkeypatch.setattr(tdx_import, "run_import", fake_import)
    args = daily_args()
    args.apply = True
    deps = FakeDeps()
    assert (
        tdx_import._execute(
            args, intraday=False, now=NOW, deps=deps, run_id="apply-fixed"
        )
        == 0
    )
    assert deps.written == [("day", [make_bar()], NOW)]
    assert len(deps.runs) == 1 and deps.runs[0][1] == TODAY
    assert deps.runs[0][0].inserted == 1
    assert capsys.readouterr().out.splitlines()[-1] == "applied"


def test_intraday_execute_caps_cutoff_and_excludes_bj(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_import(**kwargs: object) -> RunReport:
        captured.update(kwargs)
        return capture_report(kwargs)

    monkeypatch.setattr(tdx_import, "run_import", fake_import)
    deps = FakeDeps()
    deps.open_days.add(dt.date(2023, 11, 8))
    deps.first["600000.SH"] = dt.date(2023, 11, 10)
    deps.previous[dt.date(2023, 11, 10)] = UNTIL
    assert (
        tdx_import._execute(
            intraday_args(), intraday=True, now=NOW, deps=deps, run_id="minute-fixed"
        )
        == 0
    )
    assert captured["kind"] == "lc1"
    assert captured["exclude"] == frozenset({"bj"})
    assert captured["compare_amount"] is False
    until_for = cast(Callable[[str], dt.date | None], captured["until_for"])
    assert until_for("600000.SH") == dt.date(2023, 11, 8)
    assert until_for("000001.SZ") == dt.date(2023, 11, 8)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("bad-from", "from_invalid"),
        ("bad-until", "until_invalid"),
        ("exclude-daily", "scope_exclude_bj_intraday_only"),
        ("market", "market_scope_disabled"),
        ("until-today", "until_must_be_past_open_day"),
        ("until-closed", "until_must_be_past_open_day"),
        ("recommended-none", "calendar_not_covered"),
        ("until-none", "until_after_mairui_window_start"),
        ("until-after", "until_after_mairui_window_start"),
        ("from-after", "from_after_until"),
    ],
)
def test_daily_execute_refusals_stop_before_import(
    case: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def must_not_import(**kwargs: object) -> RunReport:
        pytest.fail("refused input reached run_import")

    monkeypatch.setattr(tdx_import, "run_import", must_not_import)
    args = daily_args()
    deps = FakeDeps()
    if case == "bad-from":
        args.start = "bad"
    elif case == "bad-until":
        args.until = "bad"
    elif case == "exclude-daily":
        args.scope = ("owned", frozenset({"bj"}))
    elif case == "market":
        args.scope = ("market", frozenset())
    elif case == "until-today":
        args.until = TODAY.isoformat()
    elif case == "until-closed":
        args.until = DAY.isoformat()
    elif case == "recommended-none":
        deps.recommended = None
    elif case == "until-none":
        args.until = None
    elif case == "until-after":
        args.until = "2023-11-10"
        deps.open_days.add(dt.date(2023, 11, 10))
    elif case == "from-after":
        args.start = "2023-11-10"
    assert (
        tdx_import._execute(args, intraday=False, now=NOW, deps=deps, run_id="refused")
        == 1
    )
    assert capsys.readouterr().out.splitlines()[-1] == f"refused: {expected}"


def test_intraday_refusals_and_bj_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    deps = FakeDeps()
    deps.open_days.add(dt.date(2023, 11, 8))
    deps.previous[TODAY] = None
    assert (
        tdx_import._execute(
            intraday_args(), intraday=True, now=NOW, deps=deps, run_id="no-calendar"
        )
        == 1
    )
    assert capsys.readouterr().out.strip() == "refused: calendar_not_covered"
    deps.previous.clear()

    def missing_bj(**kwargs: object) -> RunReport:
        raise TdxRefused("root_missing:bj/minline")

    monkeypatch.setattr(tdx_import, "run_import", missing_bj)
    assert (
        tdx_import._execute(
            intraday_args(), intraday=True, now=NOW, deps=deps, run_id="missing-bj"
        )
        == 1
    )
    assert capsys.readouterr().out.strip().endswith("; hint: --scope owned,exclude-bj")


def test_run_rejects_naive_now_before_dependencies(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert (
        tdx_import.daily_main(
            ["--root", "r", "--audit-dir", "a", "--until", UNTIL.isoformat()],
            now=dt.datetime(2026, 11, 10, 12, 0),
            deps=FakeDeps(),
            run_id="naive",
        )
        == 1
    )
    assert capsys.readouterr().out.strip() == "refused: now must be timezone-aware"


class FakeContext:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def __enter__(self) -> FakeConnection:
        return self.conn

    def __exit__(self, *args: object) -> None:
        return None


class FakeEngine:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn
        self.calls: list[str] = []
        self.settings: list[Settings] = []

    def connect(self) -> FakeContext:
        self.calls.append("connect")
        return FakeContext(self.conn)

    def begin(self) -> FakeContext:
        self.calls.append("begin")
        return FakeContext(self.conn)


@pytest.mark.parametrize("apply", [False, True])
def test_run_uses_expected_transaction_and_rollback(
    apply: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = FakeConnection()
    engine = FakeEngine(conn)
    settings = cast(Settings, SimpleNamespace(marker="synthetic"))
    seen: list[object] = []
    monkeypatch.setattr(tdx_import.jobs_mod, "_engine", lambda value: engine)
    monkeypatch.setattr(
        tdx_import,
        "_execute",
        lambda args, **kwargs: seen.append(kwargs) or 0,
    )
    argv = ["--root", "r", "--audit-dir", "a", "--until", UNTIL.isoformat()]
    if apply:
        argv.append("--apply")
    assert tdx_import.daily_main(argv, now=NOW, settings=settings, run_id="engine") == 0
    assert engine.calls == ["begin" if apply else "connect"]
    assert conn.rollbacks == (0 if apply else 1)
    assert isinstance(seen[0]["deps"], DbDeps)  # type: ignore[index]
    assert seen[0]["deps"].conn is conn  # type: ignore[index]


def test_public_wrappers_accept_injected_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[dict[str, object]] = []
    monkeypatch.setattr(
        tdx_import,
        "_execute",
        lambda args, **kwargs: seen.append(kwargs) or 7,
    )
    argv = [
        "--root",
        "r",
        "--audit-dir",
        "a",
        "--until",
        UNTIL.isoformat(),
    ]
    deps = FakeDeps()
    assert tdx_import.daily_main(argv, deps=deps, now=NOW, run_id="daily") == 7
    argv += ["--kind", "lc1"]
    assert tdx_import.intraday_main(argv, deps=deps, now=NOW, run_id="minute") == 7
    assert [item["deps"] for item in seen] == [deps, deps]


def test_dbdeps_open_previous_and_first_minute_day() -> None:
    stamp = dt.datetime(2023, 11, 10, 1, 0, tzinfo=dt.UTC)
    conn = FakeConnection(
        [
            FakeResult(scalar=True),
            FakeResult(scalar=None),
            FakeResult(scalar=UNTIL),
            FakeResult(scalar=stamp),
            FakeResult(scalar=None),
        ]
    )
    deps = DbDeps(cast(Connection, conn))
    assert deps.is_open(UNTIL) is True
    assert deps.is_open(DAY) is None
    assert deps.previous_open(TODAY) == UNTIL
    assert deps.first_mairui_minute_day("600000.SH") == dt.date(2023, 11, 10)
    assert deps.first_mairui_minute_day("000001.SZ") is None


def test_dbdeps_recommended_daily_until_guards_and_calculates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deps = DbDeps(cast(Connection, FakeConnection()))
    monkeypatch.setattr(
        daily_bars_backfill, "_default_trade_date", lambda conn, now: None
    )
    assert deps.recommended_daily_until(NOW) is None
    monkeypatch.setattr(
        daily_bars_backfill, "_default_trade_date", lambda conn, now: TODAY
    )
    monkeypatch.setattr(daily_bars_mod, "backfill_window_days", lambda *args: None)
    assert deps.recommended_daily_until(NOW) is None
    conn = FakeConnection(
        [FakeResult(scalar_rows=[dt.date(2023, 11, 13), dt.date(2026, 11, 6)])]
    )
    deps = DbDeps(cast(Connection, conn))
    monkeypatch.setattr(daily_bars_mod, "backfill_window_days", lambda *args: object())
    monkeypatch.setattr(deps, "previous_open", lambda day: UNTIL)
    assert deps.recommended_daily_until(NOW) == UNTIL


def test_dbdeps_normalize_security_cache_and_owned_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection(
        [
            FakeResult(
                rows=[
                    SimpleNamespace(
                        code="600000.SH", type="stock", listing_status="listed"
                    )
                ]
            )
        ]
    )
    deps = DbDeps(cast(Connection, conn))
    monkeypatch.setattr(tdx_import, "normalize_code", lambda conn, raw: "600000.SH")
    assert deps.normalize("SH600000") == "600000.SH"
    assert deps.security_of("600000.SH") == ("stock", "listed")
    assert deps.security_of("600000.SH") == ("stock", "listed")
    assert deps.security_of("000001.SZ") is None
    assert len(conn.calls) == 1
    monkeypatch.setattr(
        daily_bars_backfill, "_default_trade_date", lambda conn, now: None
    )
    with pytest.raises(TdxRefused, match="calendar_not_covered"):
        deps.owned_codes(NOW)
    monkeypatch.setattr(
        daily_bars_backfill, "_default_trade_date", lambda conn, now: TODAY
    )
    monkeypatch.setattr(tdx_import, "_approved_owners", lambda conn: {"synthetic"})
    monkeypatch.setattr(
        tdx_import, "_union_universe", lambda conn, owners, day: {"600000.SH"}
    )
    assert deps.owned_codes(NOW) == frozenset({"600000.SH"})


def existing_row(key: object) -> SimpleNamespace:
    return SimpleNamespace(
        get=lambda field: key,
        ts=key,
        trade_date=key,
        _mapping={
            "source": "synthetic",
            "open": Decimal(10),
            "high": Decimal("10.2"),
            "low": Decimal("9.8"),
            "close": Decimal("10.1"),
            "volume": Decimal(1000),
            "amount": Decimal(10100),
        },
    )


@pytest.mark.parametrize("kind", ["day", "lc1", "lc5"])
def test_dbdeps_existing_maps_daily_and_intraday_rows(kind: str) -> None:
    bar = make_bar(ts=TS if kind != "day" else None)
    key = TS if kind != "day" else DAY
    conn = FakeConnection([FakeResult(rows=[existing_row(key)])])
    deps = DbDeps(cast(Connection, conn))
    found = deps.existing(cast(Kind, kind), bar.code, [bar])
    assert found[key] == ExistingBar(
        "synthetic",
        Decimal(10),
        Decimal("10.2"),
        Decimal("9.8"),
        Decimal("10.1"),
        Decimal(1000),
        Decimal(10100),
    )


def test_dbdeps_write_daily_uses_do_nothing_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection()
    deps = DbDeps(cast(Connection, conn))
    seen: list[object] = []

    def fake_upsert(*args: object, **kwargs: object) -> SimpleNamespace:
        seen.extend([*args, kwargs])
        return SimpleNamespace(inserted=1)

    monkeypatch.setattr(tdx_import, "upsert_daily_bars", fake_upsert)
    assert deps.write("day", [make_bar()], NOW) == 1
    assert conn.calls == []
    result = seen[1]
    assert result.bars[0].code == "600000.SH"  # type: ignore[attr-defined]
    assert seen[2]["source"] == tdx_import.TDX_LOCAL_SOURCE  # type: ignore[index]


@pytest.mark.parametrize("kind", ["lc1", "lc5"])
def test_dbdeps_write_intraday_batches_without_real_db(
    kind: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = FakeConnection([FakeResult(rows=[object()]), FakeResult(rows=[object()])])
    deps = DbDeps(cast(Connection, conn))
    monkeypatch.setattr(tdx_import, "UPSERT_BATCH_ROWS", 1)
    bars = [make_bar(ts=TS), make_bar(ts=TS + dt.timedelta(minutes=1))]
    assert deps.write(cast(Kind, kind), bars, NOW) == 2
    assert len(conn.calls) == 2


def test_dbdeps_record_run_uses_report_stats() -> None:
    conn = FakeConnection()
    deps = DbDeps(cast(Connection, conn))
    report = RunReport(kind="day", run_id="synthetic", apply=True, files=1)
    deps.record_run(report, TODAY)
    assert len(conn.calls) == 1
