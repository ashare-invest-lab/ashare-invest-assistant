"""Only synthetic tests may inject the isolated BJ list."""

from collections.abc import Callable, Iterable

import pytest

from app import bj_offline_volume


@pytest.fixture
def bj_isolated_list(monkeypatch: pytest.MonkeyPatch) -> Callable[[Iterable[str]], None]:
    def inject(codes: Iterable[str]) -> None:
        monkeypatch.setattr(bj_offline_volume, "_BJ_ISOLATED_CONFIRMATIONS", frozenset(codes))

    return inject
