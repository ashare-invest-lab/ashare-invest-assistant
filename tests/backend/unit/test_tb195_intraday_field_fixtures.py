# ruff: noqa: S101
"""I1 checks synthetic normalized shapes without importing any vendor adapter."""

from __future__ import annotations

import json
import socket
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from app.marketdata.bars_read import Bar
from app.marketdata.quotes_read import QuoteItem
from app.marketdata.subresource_read import Gap

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/intraday/tb195-normalized.json"


class ProposedQuoteBasis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["intraday", "close"] | None
    trade_date: date | None
    source: str | None


class ProposedQuote(QuoteItem):
    basis: ProposedQuoteBasis


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        pytest.fail("I1 fixture checks cannot access the network")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


@pytest.fixture(scope="module")
def normalized() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("name", "mode", "quantity", "status"),
    [
        ("unknown", None, None, "unavailable"),
        ("units_unverified", "intraday", None, "partial"),
        ("confirmed_zero_close", "close", "0", "stale"),
    ],
)
def test_quote_basis_and_missing_fields_round_trip(
    normalized: dict[str, Any], name: str, mode: str | None, quantity: str | None, status: str
) -> None:
    item = normalized["quotes"][name]
    quote = ProposedQuote.model_validate_json(json.dumps(item), strict=True)
    assert json.loads(quote.model_dump_json()) == item
    assert quote.basis.mode == mode
    assert quote.volume == quote.amount == quantity
    assert quote.data_status == status
    assert quote.data_as_of == quote.t
    if mode is None:
        assert quote.basis.model_dump() == dict.fromkeys(("mode", "trade_date", "source"))
        assert quote.price is quote.change_pct is quote.t is None
    else:
        assert quote.basis.source is not None
        assert quote.basis.source.startswith("synthetic:i1:")
        assert quote.t is not None
        assert quote.price == "12.34"
        observed = datetime.fromisoformat(quote.t)
        assert observed.utcoffset() == timedelta(hours=8)
        assert observed.date() == quote.basis.trade_date
    assert [gap.reason for gap in quote.gaps] == ([] if quantity == "0" else ["no_source"])


@pytest.mark.parametrize(
    ("name", "units"), [("complete", ("100", "1234.00")), ("confirmed_zero", ("0", "0"))]
)
def test_complete_minute_preserves_decimal_strings_and_end_time(
    normalized: dict[str, Any], name: str, units: tuple[str, str]
) -> None:
    minute = normalized["minute"]
    variant = minute["variants"][name]
    item = minute["item"] | variant["overrides"]
    bar = Bar.model_validate(item)
    assert bar.model_dump(mode="json") == item
    assert (bar.volume, bar.amount) == units
    assert (minute["freq"], minute["adjust"]) == ("1m", "none")
    assert minute["source"].startswith("synthetic:i1:")
    end = datetime.fromisoformat(bar.t)
    fetched = datetime.fromisoformat(minute["fetched_at"])
    assert end.utcoffset() == fetched.utcoffset() == timedelta(hours=8)
    assert (end.hour, end.minute, end.second) == (9, 31, 0)
    assert end < fetched
    assert bar.is_final
    assert variant["emit"] is True
    assert variant["gaps"] == []


@pytest.mark.parametrize("field", ["volume", "amount"])
def test_unknown_minute_quantity_omits_the_public_bar(
    normalized: dict[str, Any], field: str
) -> None:
    minute = normalized["minute"]
    variant = minute["variants"][f"{field}_unverified"]
    assert variant["overrides"] == {field: None}
    assert variant["emit"] is False
    gaps = [Gap.model_validate(gap) for gap in variant["gaps"]]
    assert [(gap.key, gap.reason) for gap in gaps] == [(f"bars.{field}", "no_source")]
    with pytest.raises(ValidationError) as exc:
        Bar.model_validate(minute["item"] | variant["overrides"])
    assert [error["loc"] for error in exc.value.errors()] == [(field,)]
