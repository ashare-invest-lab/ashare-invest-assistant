"""Synthetic encryption and temporary-file storage; never read user imports or keys."""

from __future__ import annotations

import secrets
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.common.errors import AppError, ErrorCode
from app.config import Settings
from app.importing import storage
from cryptography.exceptions import InvalidTag
from pydantic import SecretStr


@pytest.fixture(autouse=True)
def no_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("storage unit tests must not connect to any service")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        import_storage_path=tmp_path / "imports",
        app_master_key=SecretStr(secrets.token_urlsafe(32)),
    )


@pytest.mark.parametrize("app_env", ["local", "test"])
@pytest.mark.parametrize("unset", [None, ""])
def test_development_default_root_uses_system_temp(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    app_env: str,
    unset: Any,
) -> None:
    monkeypatch.setattr(storage.tempfile, "gettempdir", lambda: str(tmp_path))
    assert storage.resolve_imports_root(unset, app_env) == tmp_path / "aia-imports"


@pytest.mark.parametrize("app_env", ["production", "staging"])
def test_unconfigured_deployed_root_is_unavailable(app_env: str) -> None:
    assert storage.resolve_imports_root(None, app_env) is None
    with pytest.raises(AppError) as error:
        storage.storage_root(SimpleNamespace(import_storage_path=None, app_env=app_env))
    assert error.value.code == ErrorCode.MAINTENANCE


def test_explicit_root_is_used_without_resolving_or_creating_it(tmp_path: Path) -> None:
    root = tmp_path / "configured"
    assert storage.resolve_imports_root(root, "production") == root
    assert storage.resolve_imports_root(str(root), "test") == root
    assert not root.exists()


@pytest.mark.parametrize("legacy", [False, True])
def test_authenticated_file_round_trip_and_legacy_header(
    settings: Settings,
    legacy: bool,
) -> None:
    data, aad = b"synthetic import bytes\x00", b"synthetic-batch"
    current = storage.encrypt_file(settings, data, aad)
    assert current.startswith(storage.MAGIC)
    assert data not in current
    identifier = storage.file_kek_id(current)
    assert identifier is not None and len(identifier) == storage.KEK_ID_LEN
    blob = storage.MAGIC_V1 + current[4 + storage.KEK_ID_LEN :] if legacy else current
    assert storage.file_kek_id(blob) == (None if legacy else identifier)
    assert storage.decrypt_file(settings, blob, aad) == data
    with pytest.raises(InvalidTag):
        storage.decrypt_file(settings, blob, b"other-synthetic-batch")


@pytest.mark.parametrize("blob", [b"", b"AIA0synthetic"])
def test_unknown_file_magic_is_rejected(blob: bytes) -> None:
    with pytest.raises(ValueError, match="bad magic"):
        storage.file_kek_id(blob)


def test_file_encrypted_with_another_synthetic_key_is_identified(
    settings: Settings,
) -> None:
    blob = storage.encrypt_file(settings, b"synthetic", b"batch")
    other = settings.model_copy(
        update={"app_master_key": SecretStr(secrets.token_urlsafe(32))}
    )
    with pytest.raises(storage.KekMismatchError, match="different KEK"):
        storage.decrypt_file(other, blob, b"batch")


def test_raw_file_round_trip_and_delete_only_fixture_file(settings: Settings) -> None:
    rel = storage.write_raw(
        settings, "synthetic-user", "synthetic-batch", b"fictional bytes"
    )
    assert rel == "synthetic-user/synthetic-batch.bin"
    root = storage.storage_root(settings)
    target = root / rel
    assert target.is_file()
    assert target.read_bytes().startswith(storage.MAGIC)
    assert storage.read_raw(settings, rel, "synthetic-batch") == b"fictional bytes"
    with pytest.raises(InvalidTag):
        storage.read_raw(settings, rel, "wrong-synthetic-batch")
    unrelated = root / "unrelated.bin"
    unrelated.write_bytes(b"synthetic bystander")
    storage.delete_raw(settings, rel)
    assert not target.exists() and unrelated.read_bytes() == b"synthetic bystander"
    storage.delete_raw(
        settings, rel
    )  # Missing file under an existing root is idempotent.
    assert unrelated.read_bytes() == b"synthetic bystander"


@pytest.mark.parametrize("operation", ["read", "delete"])
@pytest.mark.parametrize("relative", ["../outside.bin", ""])
def test_storage_escape_and_root_itself_are_rejected_before_file_access(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    relative: str,
) -> None:
    root = storage.storage_root(settings)
    root.mkdir()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("out-of-root file access must not occur")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "unlink", forbidden)
    with pytest.raises(ValueError, match="path escapes storage root"):
        if operation == "read":
            storage.read_raw(settings, relative, "synthetic-batch")
        else:
            storage.delete_raw(settings, relative)


def test_missing_storage_mount_is_not_a_successful_delete(settings: Settings) -> None:
    assert not storage.storage_root(settings).exists()
    with pytest.raises(storage.StorageRootMissingError) as error:
        storage.delete_raw(settings, "synthetic-user/missing.bin")
    assert str(error.value) == "import storage root does not exist"
    assert str(storage.storage_root(settings)) not in str(error.value)


@pytest.mark.parametrize("value", [None, "", "v0:synthetic", "plain synthetic line"])
def test_unversioned_or_absent_line_is_empty(
    settings: Settings, value: str | None
) -> None:
    assert storage.decrypt_line(settings, value) == ""


def test_masked_line_round_trip_is_randomized_and_authenticated(
    settings: Settings,
) -> None:
    masked = "纯合成已掩码行 ***"
    first = storage.encrypt_line(settings, masked)
    second = storage.encrypt_line(settings, masked)
    assert first.startswith("v1:") and second.startswith("v1:")
    assert first != second and masked not in first
    assert storage.decrypt_line(settings, first) == masked
    assert storage.decrypt_line(settings, second) == masked
    other = settings.model_copy(
        update={"app_master_key": SecretStr(secrets.token_urlsafe(32))}
    )
    with pytest.raises(InvalidTag):
        storage.decrypt_line(other, first)
