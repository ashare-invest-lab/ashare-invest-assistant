"""Explicit test-only Unix endpoints; never consult application URLs or env files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import parse_qs, unquote, urlsplit

from sqlalchemy import URL


def _socket_path(value: str, *, postgres: bool = False) -> str:
    path = PurePosixPath(value)
    if (
        not value.startswith("/tmp/")  # noqa: S108 - validate dedicated test sockets
        or str(path) != value
        or ".." in path.parts
        or any(char in value for char in ("\x00", "\n", "\r"))
        or (postgres and not value.startswith("/tmp/tb70-"))  # noqa: S108
    ):
        raise ValueError("test resources require dedicated absolute /tmp Unix sockets")
    return value


@dataclass(frozen=True)
class UnixTestResources:
    pg_socket: str
    redis_url: str

    def database_url(self, name: str) -> str:
        return URL.create(
            "postgresql+psycopg",
            username="postgres",
            database=name,
            query={"host": self.pg_socket},
        ).render_as_string(hide_password=False)


def from_env(prefix: str, *, pg_socket: str, redis_url: str) -> UnixTestResources:
    """Only named test variables may override the historical dedicated defaults."""
    pg = _socket_path(os.environ.get(prefix + "_PG_SOCKET", pg_socket), postgres=True)
    redis = os.environ.get(prefix + "_REDIS_URL", redis_url)
    parsed = urlsplit(redis)
    if (
        parsed.scheme != "unix"
        or any(char in redis for char in ("\x00", "\n", "\r", "\t"))
        or parsed.netloc
        or parsed.fragment
        or parse_qs(parsed.query, keep_blank_values=True) != {"db": ["0"]}
    ):
        raise ValueError("test Redis requires a Unix socket and isolated db=0")
    _socket_path(unquote(parsed.path, errors="strict"))
    return UnixTestResources(pg, redis)
