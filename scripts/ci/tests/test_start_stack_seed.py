"""T-O73c：start-stack.sh 在 db-roles 之后、启动 worker 之前跑 engine_policy seed。

用 stub 掉的 compose.sh / docker / db-precheck，不连库、不联网、不启真容器。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy/scripts/wrapup/start-stack.sh"

FAKE_COMPOSE = r"""#!/usr/bin/env bash
log="$FAKE_DIR/compose.log"
echo "ARGS $*" >>"$log"
case "$1" in
  --resolve|--get) echo fake; exit 0 ;;
  stop) exit 0 ;;
  ps)
    if [ "${2:-}" = "-q" ]; then echo fakepg; else echo "fake-ps"; fi
    exit 0 ;;
  up)
    echo "UP $*" >>"$log"
    case "${!#}" in
      migrate|timescale-apply|db-roles)
        # A selected one-shot service has no dependent service to tell --wait
        # that exiting 0 is success. Simulate that failure and foreground rc.
        if [[ " $* " == *" --wait "* ]]; then exit 1; fi
        if [[ " $* " == *" --exit-code-from ${!#} "* ]] && [ "${FAKE_JOB_SERVICE:-}" = "${!#}" ]; then
          exit "${FAKE_JOB_RC:-0}"
        fi
        ;;
    esac
    exit 0 ;;
  run)
    echo "RUN $*" >>"$log"
    # 不得覆盖默认 entrypoint
    if [[ "$*" == *"--entrypoint"* ]]; then echo "entrypoint-override" >&2; exit 99; fi
    if [[ "$*" != *"--rm"* ]] || [[ "$*" != *"--no-deps"* ]] || [[ "$*" != *"-T"* ]]; then
      echo "missing-run-flags" >&2; exit 99
    fi
    if [[ "$*" != *" worker "* ]] && [[ "$*" != *" worker" ]]; then
      echo "missing-worker" >&2; exit 99
    fi
    if [[ "$*" != *'python -m app.engine_policies --database-url "$DATABASE_URL"'* ]]; then
      echo "missing-seed-cmd" >&2; exit 99
    fi
    printf '%s' "${FAKE_SEED_OUT-}"
    printf '%s' "${FAKE_SEED_ERR-}" >&2
    exit "${FAKE_SEED_RC:-0}"
    ;;
esac
exit 98
"""

FAKE_DOCKER = r"""#!/usr/bin/env bash
echo "DOCKER $*" >>"$FAKE_DIR/docker.log"
cmd="$1"
shift
if [ "$cmd" = "compose" ]; then
  bash "$FAKE_DIR/bin/compose-stub.sh" "$@"
  rc=$?
  echo "RESULT compose rc=$rc" >>"$FAKE_DIR/docker.log"
  exit "$rc"
fi
# docker info
if [ "$cmd" = "info" ]; then exit 0; fi
if [ "$cmd" != "exec" ]; then exit 0; fi
# skip -e KEY=val
while [ $# -gt 0 ]; do
  case "$1" in
    -e) shift 2 ;;
    *) break ;;
  esac
done
# remaining: container + command
if [[ "$*" == *"SELECT version_num FROM alembic_version"* ]]; then
  echo "QUERY $*" >>"$FAKE_DIR/docker.log"
  # The production query must leave the container role and target-db fallback
  # expression for the container shell to expand.  Host-side defaults are the
  # regressions this shim rejects.
  if [[ "$*" != *'"$POSTGRES_USER"'* ]] || [[ "$*" != *'"${AIA_TARGET_DB:-$POSTGRES_DB}"'* ]]; then
    echo 'role "postgres" does not exist' >&2
    exit 1
  fi
  printf '0028\n'
  exit 0
fi
exit 0
"""

FAKE_PRECHECK = r"""#!/usr/bin/env bash
echo "PRECHECK $*" >>"$FAKE_DIR/precheck.log"
exit 0
"""


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    dest = tmp_path / "20260101T000000Z"
    dest.mkdir()
    (dest / "manifest.json").write_text("{}\n", encoding="utf-8")
    dump = dest / "aia.dump"
    dump.write_bytes(b"dump")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    compose = bindir / "compose.sh"
    # Bypass the real compose wrapper: never read .env or any secret files.
    compose.write_text(
        '#!/usr/bin/env bash\nexec docker compose "$@"\n', encoding="utf-8"
    )
    compose.chmod(0o755)
    (bindir / "compose-stub.sh").write_text(FAKE_COMPOSE, encoding="utf-8")
    docker = bindir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    pre = bindir / "db-precheck.sh"
    pre.write_text(FAKE_PRECHECK, encoding="utf-8")
    pre.chmod(0o755)
    return tmp_path


def _run(
    fake: Path, *args: str, script: Path = SCRIPT, **extra: str
) -> subprocess.CompletedProcess[str]:
    dest = fake / "20260101T000000Z"
    env = {
        "PATH": str(fake / "bin") + os.pathsep + os.environ["PATH"],
        "HOME": str(fake),
        "XDG_RUNTIME_DIR": str(fake),
        "FAKE_DIR": str(fake),
        "COMPOSE": str(fake / "bin" / "compose.sh"),
        "WRAPUP_DB_PRECHECK": str(fake / "bin" / "db-precheck.sh"),
        "UP_WAIT_TIMEOUT": "1",
        "FAKE_SEED_OUT": "engine_policy_seed_inserted=1\n",
        "FAKE_SEED_ERR": "",
        "FAKE_SEED_RC": "0",
    }
    env.update(extra)
    return subprocess.run(
        [
            "bash",
            str(script),
            *args,
            "--backup-dir",
            str(dest),
            "--container",
            "fakepg",
            "--db",
            "aia",
            "--volume-prefix",
            "o69",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _copy_script(fake: Path, *, mutate_credentials: bool = False) -> Path:
    wrapup = fake / "wrapup"
    wrapup.mkdir(exist_ok=True)
    script = wrapup / "start-stack.sh"
    text = SCRIPT.read_text(encoding="utf-8")
    if mutate_credentials:
        old = 'psql -X -q -At -U "$POSTGRES_USER" -d "${AIA_TARGET_DB:-$POSTGRES_DB}"'
        text = text.replace(
            old,
            'psql -X -q -At -U "${POSTGRES_USER:-postgres}" -d "${AIA_TARGET_DB:-$POSTGRES_DB}"',
        )
        assert text != SCRIPT.read_text(encoding="utf-8")
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    shutil.copy(SCRIPT.parent / "lib.sh", wrapup / "lib.sh")
    return script


def _compose_log(fake: Path) -> str:
    p = fake / "compose.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _receipt(fake: Path) -> str | None:
    p = fake / "20260101T000000Z" / "engine_policy_seed.txt"
    return p.read_text(encoding="utf-8") if p.exists() else None


def _worker_up(log: str) -> bool:
    return any(("UP " in line and "worker" in line) for line in log.splitlines())


def _seed_run(log: str) -> bool:
    return any(line.startswith("RUN ") for line in log.splitlines())


@pytest.mark.parametrize("inserted", ["1", "0"])
def test_seed_inserted_continues_and_starts_worker(fake: Path, inserted: str) -> None:
    r = _run(fake, "--apply", FAKE_SEED_OUT=f"engine_policy_seed_inserted={inserted}\n")
    assert r.returncode == 0, r.stderr
    assert _receipt(fake) == f"engine_policy_seed_inserted={inserted}\n"
    log = _compose_log(fake)
    assert _seed_run(log)
    assert _worker_up(log)
    # seed RUN 出现在 worker UP 之前
    run_at = min(
        i for i, line in enumerate(log.splitlines()) if line.startswith("RUN ")
    )
    up_at = min(
        i
        for i, line in enumerate(log.splitlines())
        if "UP " in line and "worker" in line
    )
    assert run_at < up_at
    assert "--entrypoint" not in log
    assert "postgresql" not in r.stdout + r.stderr
    assert "PASSWORD" not in r.stdout + r.stderr


def test_hash_conflict_stops_without_starting_worker(fake: Path) -> None:
    r = _run(
        fake,
        "--apply",
        FAKE_SEED_OUT="",
        FAKE_SEED_ERR="ValueError: engine_policy_version_hash_conflict\n",
        FAKE_SEED_RC="1",
    )
    assert r.returncode != 0, r.stderr
    assert "engine_policy_version_hash_conflict" in r.stderr
    assert "不启动 worker" in r.stderr
    assert "不删除旧行" in r.stderr
    assert _receipt(fake) is None
    log = _compose_log(fake)
    assert _seed_run(log)
    assert not _worker_up(log)


def test_nonzero_rc_stops_without_starting_worker(fake: Path) -> None:
    r = _run(
        fake, "--apply", FAKE_SEED_OUT="", FAKE_SEED_ERR="boom\n", FAKE_SEED_RC="3"
    )
    assert r.returncode != 0, r.stderr
    assert "退出码为 3" in r.stderr
    assert "不启动 worker" in r.stderr
    assert _receipt(fake) is None
    log = _compose_log(fake)
    assert _seed_run(log)
    assert not _worker_up(log)


@pytest.mark.parametrize(
    "out",
    [
        "",
        "not-a-result\n",
        "engine_policy_seed_inserted=2\n",
        "engine_policy_seed_inserted=1\nextra\n",
    ],
)
def test_unparseable_output_stops_without_starting_worker(fake: Path, out: str) -> None:
    r = _run(fake, "--apply", FAKE_SEED_OUT=out, FAKE_SEED_RC="0")
    assert r.returncode != 0, r.stderr
    assert "无法解析" in r.stderr
    assert "不启动 worker" in r.stderr
    assert _receipt(fake) is None
    log = _compose_log(fake)
    assert _seed_run(log)
    assert not _worker_up(log)


def test_dry_run_prints_seed_and_does_not_execute(fake: Path) -> None:
    r = _run(fake)  # no --apply
    assert r.returncode == 0, r.stderr
    assert "engine_policy seed" in r.stderr
    assert "python -m app.engine_policies --database-url" in r.stderr
    assert "将要执行（未写入）" in r.stderr
    assert "已写入本轮收据" not in r.stderr
    assert _receipt(fake) is None
    assert _compose_log(fake) == ""
    assert not (fake / "20260101T000000Z" / "engine_policy_seed.txt").exists()


def test_hash_conflict_rc0_stops_without_starting_worker(fake: Path) -> None:
    """T-A121 / T-A125⑦：stdout 为合法 inserted=1，同时 stderr 带冲突标记且 rc=0。
    必须走冲突检查并停下；若 OUT 为空会误走「无法解析」，去掉冲突检查后用例仍绿。
    """
    r = _run(
        fake,
        "--apply",
        FAKE_SEED_OUT="engine_policy_seed_inserted=1\n",
        FAKE_SEED_ERR="ValueError: engine_policy_version_hash_conflict\n",
        FAKE_SEED_RC="0",
    )
    assert r.returncode != 0, r.stderr
    assert "engine_policy_version_hash_conflict：立即停止" in r.stderr
    assert "不启动 worker" in r.stderr
    assert "不删除旧行" in r.stderr
    assert "无法解析" not in r.stderr
    assert _receipt(fake) is None
    log = _compose_log(fake)
    assert _seed_run(log)
    assert not _worker_up(log)


@pytest.mark.parametrize(
    "out",
    [
        "engine_policy_seed_inserted=1\r\n",
        "\r\nengine_policy_seed_inserted=1\r\n",
        "engine_policy_seed_inserted=0\r\n",
    ],
)
def test_crlf_output_is_accepted_and_starts_worker(fake: Path, out: str) -> None:
    """T-A121：输出带 \\r（CRLF 或前后空行）仍判通过并启 worker，不能当成无法解析。"""
    r = _run(fake, "--apply", FAKE_SEED_OUT=out)
    assert r.returncode == 0, r.stderr
    val = "0" if "inserted=0" in out else "1"
    assert _receipt(fake) == f"engine_policy_seed_inserted={val}\n"
    log = _compose_log(fake)
    assert _seed_run(log)
    assert _worker_up(log)


def test_one_shot_jobs_use_exit_codes_and_only_daemons_wait(fake: Path) -> None:
    r = _run(fake, "--apply")
    assert r.returncode == 0, r.stdout + r.stderr
    commands = [
        line.removeprefix("DOCKER compose ")
        for line in (fake / "docker.log").read_text(encoding="utf-8").splitlines()
        if line.startswith("DOCKER compose up ")
    ]
    assert len(commands) == 5, commands
    assert commands[0].endswith("--no-deps postgres redis")
    assert commands[-1].endswith("--no-deps api worker beat ingest signal-rt nginx")
    for command in (commands[0], commands[-1]):
        assert "--wait" in command.split() and "-d" in command.split()
    for command, service in zip(
        commands[1:4], ("migrate", "timescale-apply", "db-roles")
    ):
        assert command.split() == [
            "up",
            "--build",
            "--no-deps",
            "--exit-code-from",
            service,
            service,
        ]
    log = _compose_log(fake)
    assert log.index("UP up --build --no-deps --exit-code-from db-roles") < log.index(
        "RUN run"
    )
    assert _receipt(fake) == "engine_policy_seed_inserted=1\n"


@pytest.mark.parametrize("service", ["migrate", "timescale-apply", "db-roles"])
@pytest.mark.parametrize("rc", [1, 7])
def test_one_shot_failure_stops_all_later_steps(
    fake: Path, service: str, rc: int
) -> None:
    r = _run(fake, "--apply", FAKE_JOB_SERVICE=service, FAKE_JOB_RC=str(rc))
    assert r.returncode == rc, r.stdout + r.stderr
    assert f"{service} 退出码为 {rc}" in r.stderr
    log = _compose_log(fake)
    assert not _seed_run(log)
    assert not _worker_up(log)
    assert _receipt(fake) is None
    jobs = ["migrate", "timescale-apply", "db-roles"]
    for later in jobs[jobs.index(service) + 1 :]:
        assert not any(
            line.startswith("UP ") and line.endswith(f" {later}")
            for line in log.splitlines()
        )
    calls = (fake / "docker.log").read_text(encoding="utf-8")
    assert f"RESULT compose rc={rc}" in calls


def test_dry_run_describes_foreground_one_shot_jobs(fake: Path) -> None:
    r = _run(fake)
    assert r.returncode == 0, r.stderr
    for service in ("migrate", "timescale-apply", "db-roles"):
        line = next(
            line
            for line in r.stderr.splitlines()
            if f"--exit-code-from {service} {service}" in line
        )
        assert "--wait" not in line and " -d " not in line
    assert _compose_log(fake) == ""
    assert not (fake / "docker.log").exists()


def test_alembic_query_uses_container_credentials(fake: Path) -> None:
    r = _run(fake, "--apply")
    assert r.returncode == 0, r.stderr
    query = next(
        line
        for line in (fake / "docker.log").read_text(encoding="utf-8").splitlines()
        if line.startswith("QUERY ")
    )
    assert '"$POSTGRES_USER"' in query
    assert '"${AIA_TARGET_DB:-$POSTGRES_DB}"' in query
    assert '"$POSTGRES_DB"' not in query
    assert '"${POSTGRES_USER:-postgres}"' not in query
    assert '"postgres"' not in query
    docker = (fake / "docker.log").read_text(encoding="utf-8")
    assert "-e AIA_TARGET_DB=aia" in docker


def test_alembic_query_credential_mutation_is_red(fake: Path) -> None:
    mutated = _copy_script(fake, mutate_credentials=True)
    r = _run(fake, "--apply", script=mutated)
    assert r.returncode != 0
    assert 'role "postgres" does not exist' in r.stderr
    assert "拒绝 migrate" in r.stderr
