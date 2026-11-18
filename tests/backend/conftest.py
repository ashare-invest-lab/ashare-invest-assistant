"""后端测试共享 fixture（T-T01）：测试库容器。

plan §3A.1/§8.0：单元与集成测试都用 PostgreSQL（testcontainers），不用 SQLite；
镜像与 deploy/compose/docker-compose.yml 保持一致（timescale/timescaledb:2.31.0-pg16、redis:7.4.12-alpine）。

- Docker 不可用（未安装、daemon 未运行、无权限）时，依赖这些 fixture 的用例 **skip**，不报错。
- `AIA_TEST_DATABASE_URL` / `AIA_TEST_REDIS_URL`：指向已有实例（例如 CI service container），
  设置后不再启动容器，直接复用。
- 账号口令只用于一次性容器，固定为测试占位值，不是任何环境的真实口令。
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable, Iterator
from ipaddress import IPv4Network
from itertools import chain

import pytest

PG_IMAGE = os.environ.get("AIA_TEST_PG_IMAGE", "timescale/timescaledb:2.31.0-pg16")
REDIS_IMAGE = os.environ.get("AIA_TEST_REDIS_IMAGE", "redis:7.4.12-alpine")


def docker_unavailable_reason() -> str | None:
    """返回 None 表示 Docker 可用；否则返回 skip 原因。"""
    try:
        import docker  # testcontainers 的依赖
    except ImportError:  # pragma: no cover
        return "未安装 docker SDK（pip install -r tests/requirements.txt）"
    try:
        client = docker.from_env(timeout=5)
        client.ping()
        client.close()
    except Exception as exc:  # noqa: BLE001 - 任何原因都视为不可用
        return f"Docker 不可用，跳过测试容器用例：{type(exc).__name__}: {exc}"
    return None


@pytest.fixture(scope="session")
def docker_available() -> None:
    reason = docker_unavailable_reason()
    if reason:
        pytest.skip(reason)


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    """会话级 PostgreSQL 16 + TimescaleDB；返回 psycopg 可用的 `postgresql://` URL。"""
    preset = os.environ.get("AIA_TEST_DATABASE_URL")
    if preset:
        yield preset
        return
    reason = docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    try:
        from testcontainers.community.postgres import PostgresContainer  # type: ignore[import-not-found]
    except ImportError:
        from testcontainers.postgres import PostgresContainer

    container = PostgresContainer(
        PG_IMAGE, username="aia_test", password="aia_test", dbname="aia_test", driver=None
    )
    with container:
        yield container.get_connection_url()


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    preset = os.environ.get("AIA_TEST_REDIS_URL")
    if preset:
        yield preset
        return
    reason = docker_unavailable_reason()
    if reason:
        pytest.skip(reason)
    try:
        from testcontainers.community.redis import RedisContainer  # type: ignore[import-not-found]
    except ImportError:
        from testcontainers.redis import RedisContainer

    with RedisContainer(REDIS_IMAGE) as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6379)
        yield f"redis://{host}:{port}/0"


@pytest.fixture(scope="session")
def next_auth_client_ip() -> Callable[[], str]:
    """从同一池分配测试来源，防止动态导入的认证夹具复用 Redis 限流桶。"""
    network = IPv4Network("198.18.0.0/15")
    start = secrets.randbelow(network.num_addresses)
    offsets = chain(range(start, network.num_addresses), range(start))

    def allocate() -> str:
        offset = next(offsets, None)
        if offset is None:
            raise RuntimeError("认证测试来源 IP 池耗尽")
        return str(network.network_address + offset)

    return allocate


@pytest.fixture()
def pg_conn(pg_url: str):  # type: ignore[no-untyped-def]
    """每个用例一个连接，事务结束后回滚，用例之间互不污染。"""
    import psycopg

    with psycopg.connect(pg_url, autocommit=False) as conn:
        yield conn
        conn.rollback()
