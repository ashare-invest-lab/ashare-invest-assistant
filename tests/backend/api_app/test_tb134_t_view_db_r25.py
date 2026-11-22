"""Run original test_tb134_t_view_db assertions in the CI-owned migrated database harness."""

from collections.abc import Iterator
from types import SimpleNamespace
from uuid import UUID

import pytest
from selfchecks import test_tb134_t_view_db as source_tests
from sqlalchemy import Engine

from .test_auth_t_b03 import authdb  # noqa: F401

test_t_view_history_cached_once_per_day = source_tests.test_t_view_history_cached_once_per_day
test_t_view_ignores_tdx_local = source_tests.test_t_view_ignores_tdx_local
test_t_view_volume_ratio_null_not_cached = source_tests.test_t_view_volume_ratio_null_not_cached
test_t_view_volume_ratio_skips_suspended_days = (
    source_tests.test_t_view_volume_ratio_skips_suspended_days
)


@pytest.fixture(autouse=True)
def compliant_intraday_fixture_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind synthetic mairui minute rows to a fictional licence under 0039."""

    original = source_tests._row
    licence_id = UUID("00000000-0000-0000-0000-0000000134d0")

    def row(*args: object, **kwargs: object) -> dict[str, object]:
        values = original(*args, **kwargs)
        if values["source"] == "mairui":
            values["source_licence_id"] = licence_id
        return values

    monkeypatch.setattr(source_tests, "_row", row)


@pytest.fixture(scope="module")
def db(authdb: SimpleNamespace) -> Iterator[Engine]:  # noqa: F811
    assert authdb.name.startswith("tt01d_auth_")
    assert authdb.engine.url.database == authdb.name
    yield authdb.engine
