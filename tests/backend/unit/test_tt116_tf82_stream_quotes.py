"""T-T116/T-F82: synthetic public quote and stream acceptance checks."""

from __future__ import annotations

import inspect

import pytest

from app.api.v1 import notifications
from tests.backend.unit.test_quotes_empty_s3 import CODE, world  # noqa: F401


def test_quotes_public_response_has_only_contract_status_fields(world):
    response = world.client.get("/api/v1/quotes", params={"codes": CODE})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert set(item) == {
        "security_code",
        "name",
        "price",
        "change_pct",
        "volume",
        "amount",
        "t",
        "data_status",
        "data_as_of",
        "gaps",
    }
    assert "source" not in item
    assert "basis" not in item
    assert item["data_status"] == "unavailable"
    assert all(item[field] is None for field in ("price", "change_pct", "volume", "amount", "t", "data_as_of"))
    assert item["gaps"][0]["reason"] == "no_source"


@pytest.mark.xfail(
    strict=True,
    reason="R376：quote 发布路径另派，不在 #376/#377",
)
def test_stream_public_entry_publishes_quote_events():
    stream_route = next(route for route in notifications.router.routes if getattr(route, "path", None) == "/stream")
    source = inspect.getsource(stream_route.endpoint)
    assert '"quote"' in source
