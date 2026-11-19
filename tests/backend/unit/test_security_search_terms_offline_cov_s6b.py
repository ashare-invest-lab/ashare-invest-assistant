"""Exercise the explicit public-term CLI without a database, provider, or real DSN."""

from __future__ import annotations

import json
import runpy
import socket
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from app.cli import security_search_terms as cli


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("CLI coverage must not connect to any service")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(cli, "create_engine", denied)
    monkeypatch.setattr(cli, "rebuild", denied)


def test_default_cli_is_a_configuration_only_dry_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main([]) == 0
    assert capsys.readouterr().out == (
        "search terms configuration validated; dry-run; no database access\n"
    )


@pytest.mark.parametrize("codes", ["999999", "999999.XX", "", "999999.SH,", "-1.SZ"])
def test_bad_codes_are_rejected_before_any_database_access(
    capsys: pytest.CaptureFixture[str], codes: str
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--apply", f"--codes={codes}"])
    assert stopped.value.code == 2
    output = capsys.readouterr()
    assert "canonical six-digit codes" in output.err
    assert output.out == ""


def test_apply_requires_an_explicit_dsn(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli.main(["--apply"])
    assert stopped.value.code == 2
    assert "--apply requires DATABASE_URL" in capsys.readouterr().err


@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize("codes", [None, "999999.sh, 000001.sz,999999.SH"])
def test_apply_normalizes_scope_commits_or_rolls_back_and_always_disposes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    fail: bool,
    codes: str | None,
) -> None:
    import yaml

    config = yaml.safe_load(
        (Path(__file__).resolve().parents[3] / "config/securities.yaml").read_text(
            encoding="utf-8"
        )
    )
    config["search"]["initials_max_variants"] = 3
    (tmp_path / "securities.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setenv(
        "DATABASE_URL", "sqlite://"
    )  # Synthetic identifier; never opened.
    events: list[object] = []
    connection = object()

    class Engine:
        @contextmanager
        def begin(self) -> Any:
            events.append("begin")
            try:
                yield connection
            except RuntimeError:
                events.append("rollback")
                raise
            else:
                events.append("commit")

        def dispose(self) -> None:
            events.append("dispose")

    def engine(dsn: str, *, hide_parameters: bool) -> Engine:
        assert dsn == "sqlite://"
        assert hide_parameters is True
        events.append("engine")
        return Engine()

    def rebuild(
        conn: object, selected: list[str] | None, *, maximum: int
    ) -> dict[str, int]:
        assert conn is connection
        assert selected == (None if codes is None else ["000001.SZ", "999999.SH"])
        assert maximum == 3
        events.append("rebuild")
        if fail:
            raise RuntimeError("synthetic rebuild failure")
        return {"securities": 2, "terms": 4}

    monkeypatch.setattr(cli, "create_engine", engine)
    monkeypatch.setattr(cli, "rebuild", rebuild)
    argv = ["--config-dir", str(tmp_path), "--apply"]
    if codes is not None:
        argv += ["--codes", codes]
    if fail:
        with pytest.raises(RuntimeError, match="synthetic rebuild failure"):
            cli.main(argv)
        assert events == ["engine", "begin", "rebuild", "rollback", "dispose"]
        assert capsys.readouterr().out == ""
    else:
        assert cli.main(argv) == 0
        assert events == ["engine", "begin", "rebuild", "commit", "dispose"]
        assert json.loads(capsys.readouterr().out) == {"securities": 2, "terms": 4}


def test_module_entry_keeps_dry_run_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["security_search_terms"])
    with pytest.raises(SystemExit) as stopped:
        runpy.run_path(str(Path(cli.__file__)), run_name="__main__")
    assert stopped.value.code == 0
    assert "dry-run; no database access" in capsys.readouterr().out
