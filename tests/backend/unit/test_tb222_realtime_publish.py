"""T-B222 quote publication uses only synthetic responses and Redis."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

from app.marketdata.realtime_publish import build_quote_data, publish_quote


OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
AT = dt.datetime(2030, 6, 11, 2, 0, tzinfo=dt.UTC)


def _response(*items: object) -> SimpleNamespace:
    return SimpleNamespace(items=list(items))


def _item(code: str, stamp: str, price: str = "10.00") -> SimpleNamespace:
    return SimpleNamespace(
        security_code=code,
        name="虚构证券",
        price=price,
        change_pct="1.00",
        amount="1000",
        t=stamp,
    )


class _Redis:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, str, dict[str, object], dt.datetime, str]] = []


def test_build_quote_data_has_contract_shape_and_earliest_time() -> None:
    data = build_quote_data(
        _response(_item("999992.SZ", "2030-06-11T09:32:00+08:00"), _item("999991.SH", "2030-06-11T09:31:00+08:00"))
    )
    assert data is not None
    assert set(data) == {"items", "data_as_of"}
    assert data["data_as_of"] == "2030-06-11T09:31:00+08:00"
    assert set(data["items"][0]) == {
        "security_code",
        "name",
        "price",
        "change_pct",
        "amount",
        "t",
    }


def test_empty_times_are_not_published() -> None:
    assert build_quote_data(_response(SimpleNamespace(t=None))) is None


def test_publish_quote_uses_content_token_and_is_best_effort(monkeypatch) -> None:
    rds = _Redis()
    seen: list[tuple[object, ...]] = []

    def fake_publish(rds_arg, owner, kind, data, at, token):
        seen.append((rds_arg, owner, kind, data, at, token))

    monkeypatch.setattr("app.marketdata.realtime_publish.publish", fake_publish)
    assert publish_quote(rds, OWNER, _response(_item("999991.SH", "2030-06-11T09:31:00+08:00")), AT)
    assert seen[0][1:3] == (OWNER, "quote")
    assert isinstance(seen[0][-1], str) and len(seen[0][-1]) == 64

    def broken(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic redis failure")

    monkeypatch.setattr("app.marketdata.realtime_publish.publish", broken)
    assert not publish_quote(rds, OWNER, _response(_item("999991.SH", "2030-06-11T09:31:00+08:00")), AT)
