"""T-B231 realtime freshness keys, using only an in-memory Redis fake."""

# Test assertions are intentional and are covered by the repository's pytest lint convention.
# ruff: noqa: S101

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.marketdata import realtime_collect


class FakeRedis:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.error = error

    def set(self, key: object, value: object, **kwargs: object) -> bool:
        if self.error is not None:
            raise self.error
        self.calls.append((key, value, kwargs))
        return True


def _settings(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "redis_url": None,
        "health_check_timeout_s": 1.0,
        "intraday_quotes_ts_key": "realtime:quotes:last_ts",
        "intraday_trading_day_key": "realtime:quotes:trading_day",
        "intraday_quotes_ts_ttl_s": None,
        "intraday_trading_day_ttl_s": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def _live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIRUI_MODE", "live")


def _call_map(fake: FakeRedis) -> dict[object, tuple[object, ...]]:
    return {call[0]: call for call in fake.calls}


def test_success_writes_latest_epoch_with_default_key() -> None:
    fake = FakeRedis()
    latest = dt.datetime(2030, 6, 11, 2, 0, 7, 900_000, tzinfo=dt.UTC)

    realtime_collect.write_realtime_freshness_keys(
        _settings(), latest_snapshot_ts=latest, redis_client=fake
    )

    calls = _call_map(fake)
    assert calls["realtime:quotes:last_ts"][1] == "1907373607"
    assert calls["realtime:quotes:last_ts"][2] == {}
    assert calls["realtime:quotes:last_ts"][1].isdigit()


@pytest.mark.parametrize(("is_open", "expected"), [(True, "1"), (False, "0")])
def test_trading_day_marker_uses_calendar_value(is_open: bool, expected: str) -> None:
    fake = FakeRedis()

    realtime_collect.write_realtime_freshness_keys(
        _settings(), trading_day_is_open=is_open, redis_client=fake
    )

    calls = _call_map(fake)
    assert calls["realtime:quotes:trading_day"][1] == expected


def test_ttl_is_omitted_by_default_and_sent_when_positive() -> None:
    without_ttl = FakeRedis()
    realtime_collect.write_realtime_freshness_keys(
        _settings(),
        trading_day_is_open=True,
        latest_snapshot_ts=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
        redis_client=without_ttl,
    )
    assert all(call[2] == {} for call in without_ttl.calls)

    with_ttl = FakeRedis()
    realtime_collect.write_realtime_freshness_keys(
        _settings(intraday_quotes_ts_ttl_s=31, intraday_trading_day_ttl_s=17),
        trading_day_is_open=True,
        latest_snapshot_ts=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
        redis_client=with_ttl,
    )
    calls = _call_map(with_ttl)
    assert calls["realtime:quotes:last_ts"][2] == {"ex": 31}
    assert calls["realtime:quotes:trading_day"][2] == {"ex": 17}


def test_keys_can_be_overridden_by_settings() -> None:
    fake = FakeRedis()

    realtime_collect.write_realtime_freshness_keys(
        _settings(
            intraday_quotes_ts_key="custom:quotes:ts",
            intraday_trading_day_key="custom:quotes:day",
        ),
        trading_day_is_open=False,
        latest_snapshot_ts=dt.datetime(2030, 1, 1, tzinfo=dt.UTC),
        redis_client=fake,
    )

    assert [call[0] for call in fake.calls] == ["custom:quotes:day", "custom:quotes:ts"]


def test_environment_names_populate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTRADAY_QUOTES_TS_KEY", "env:quotes:ts")
    monkeypatch.setenv("INTRADAY_TRADING_DAY_KEY", "env:quotes:day")
    monkeypatch.setenv("INTRADAY_QUOTES_TS_TTL_S", "31")
    monkeypatch.setenv("INTRADAY_TRADING_DAY_TTL_S", "17")

    settings = Settings()

    assert settings.intraday_quotes_ts_key == "env:quotes:ts"
    assert settings.intraday_trading_day_key == "env:quotes:day"
    assert settings.intraday_quotes_ts_ttl_s == 31
    assert settings.intraday_trading_day_ttl_s == 17


class _Context:
    def __init__(self, value: object) -> None:
        self.value = value

    def __enter__(self) -> object:
        return self.value

    def __exit__(self, *_args: object) -> bool:
        return False


class _Engine:
    def __init__(self) -> None:
        self.connection = Mock()

    def begin(self) -> _Context:
        return _Context(self.connection)


def test_zero_insert_does_not_write_last_ts(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(realtime_quotes_source="mairui")
    engine = _Engine()
    fake = FakeRedis()
    now = dt.datetime(2030, 6, 11, 2, 0, tzinfo=dt.UTC)
    monkeypatch.setattr(
        realtime_collect,
        "_open_clock",
        lambda *_args: SimpleNamespace(
            trade_date=now.date(), session=SimpleNamespace(value="morning")
        ),
    )
    monkeypatch.setattr(realtime_collect, "_trading_day_is_open", lambda *_args: True)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: uuid.uuid4())
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])
    monkeypatch.setattr(
        realtime_collect,
        "_fetch_with_egress",
        lambda *_args, **_kwargs: (200, [{"code": "600000.SH", "ts": now}]),
    )
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: 0)

    assert (
        realtime_collect.collect_realtime_quotes(
            engine.connection,
            settings,
            owner=uuid.uuid4(),
            now=now,
            engine=engine,
            redis_client=fake,
        )
        == 0
    )
    assert [call[0] for call in fake.calls] == ["realtime:quotes:trading_day"]


def test_successful_insert_writes_latest_last_ts(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings(realtime_quotes_source="mairui")
    engine = _Engine()
    fake = FakeRedis()
    now = dt.datetime(2030, 6, 11, 2, 0, 7, tzinfo=dt.UTC)
    monkeypatch.setattr(
        realtime_collect,
        "_open_clock",
        lambda *_args: SimpleNamespace(
            trade_date=now.date(), session=SimpleNamespace(value="morning")
        ),
    )
    monkeypatch.setattr(realtime_collect, "_trading_day_is_open", lambda *_args: True)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: uuid.uuid4())
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])
    monkeypatch.setattr(
        realtime_collect,
        "_fetch_with_egress",
        lambda *_args, **_kwargs: (200, [{"code": "600000.SH", "ts": now}]),
    )
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: 1)

    assert (
        realtime_collect.collect_realtime_quotes(
            engine.connection,
            settings,
            owner=uuid.uuid4(),
            now=now,
            engine=engine,
            redis_client=fake,
        )
        == 1
    )
    calls = _call_map(fake)
    assert calls["realtime:quotes:trading_day"][1] == "1"
    assert calls["realtime:quotes:last_ts"][1] == str(int(now.timestamp()))
    assert calls["realtime:quotes:last_ts"][2] == {}


def test_redis_failure_does_not_fail_collection(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    settings = _settings(realtime_quotes_source="mairui")
    fake = FakeRedis(error=RuntimeError("synthetic redis failure"))
    now = dt.datetime(2030, 6, 11, 2, 0, tzinfo=dt.UTC)
    engine = _Engine()
    monkeypatch.setattr(
        realtime_collect,
        "_open_clock",
        lambda *_args: SimpleNamespace(
            trade_date=now.date(), session=SimpleNamespace(value="morning")
        ),
    )
    monkeypatch.setattr(realtime_collect, "_trading_day_is_open", lambda *_args: True)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: uuid.uuid4())
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])
    monkeypatch.setattr(
        realtime_collect,
        "_fetch_with_egress",
        lambda *_args, **_kwargs: (200, [{"code": "600000.SH", "ts": now}]),
    )
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: 1)

    with caplog.at_level("WARNING"):
        result = realtime_collect.collect_realtime_quotes(
            engine.connection,
            settings,
            owner=uuid.uuid4(),
            now=now,
            engine=engine,
            redis_client=fake,
        )

    assert result == 1
    assert "Redis 写入失败" in caplog.text
