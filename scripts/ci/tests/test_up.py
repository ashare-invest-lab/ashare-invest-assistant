"""T-O85b: run a copied up.sh with fake compose/docker, never a real stack or env."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "deploy/scripts"

FAKE_DOCKER = r'''
import json
import os
import sys
from pathlib import Path

root = Path(os.environ["FAKE_DIR"])
args = sys.argv[1:]
with (root / "calls.jsonl").open("a") as log:
    log.write(json.dumps(args) + "\n")
if args == ["info"]:
    sys.exit(0)
assert args[0] == "compose", args
args = args[1:]
if args == ["--resolve"]:
    print("fake project")
elif args[:1] == ["--get"]:
    print(root / "presence-only" if args[1] == "AIA_SECRETS_DIR" else "fake")
elif args == ["config", "--services"]:
    specs = json.loads((root / "config.json").read_text())["services"]
    profiles = set(os.environ.get("COMPOSE_PROFILES", "").split(","))
    selected = os.environ.get("FAKE_DEFAULT_NAMES")
    if selected is not None:
        print(selected)
    else:
        for name, spec in specs.items():
            if not spec.get("profiles") or "*" in profiles or profiles.intersection(spec["profiles"]):
                print(name)
    sys.exit(int(os.environ.get("FAKE_SERVICES_RC", "0")))
elif args == ["--profile", "*", "config", "--format", "json"]:
    sys.stdout.write((root / "config.json").read_text())
    sys.exit(int(os.environ.get("FAKE_CONFIG_RC", "0")))
elif args[:1] == ["up"]:
    if "--exit-code-from" in args:
        service = args[args.index("--exit-code-from") + 1]
        assert args[-1] == service
        assert not {"-d", "--detach", "--wait", "--wait-timeout"}.intersection(args)
        if service == os.environ.get("FAKE_FAIL_JOB"):
            sys.exit(int(os.environ["FAKE_JOB_RC"]))
    else:
        assert "-d" in args and "--wait" in args and "--no-deps" in args
        sys.exit(int(os.environ.get("FAKE_RESIDENT_RC", "0")))
elif args == ["ps", "-a"]:
    print("fake ps")
else:
    raise AssertionError(args)
'''


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    scripts = tmp_path / "deploy/scripts"
    scripts.mkdir(parents=True)
    for name in ("up.sh", "up-plan.py"):
        shutil.copyfile(SCRIPTS / name, scripts / name)
    compose = scripts / "compose.sh"
    compose.write_text('#!/usr/bin/env bash\nexec docker compose "$@"\n')
    compose.chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
    docker.chmod(0o755)
    # No key contents or env files: existence checks see empty placeholder directories.
    for name in ("data_licence_seal_private_keys", "data_licence_seal_public_keys"):
        (tmp_path / "presence-only" / name).mkdir(parents=True)
    spec = yaml.safe_load((REPO / "deploy/compose/docker-compose.yml").read_text())
    # Only service metadata enters the stub; no interpolated environment or secrets.
    services = {
        name: {key: value for key, value in service.items()
               if key in {"restart", "profiles", "depends_on"}}
        for name, service in spec["services"].items()
    }
    (tmp_path / "config.json").write_text(json.dumps({"services": services}))
    return tmp_path


def run(fake: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": f"{fake / 'bin'}:{os.environ['PATH']}",
        "HOME": str(fake), "FAKE_DIR": str(fake), "UP_WAIT_TIMEOUT": "19",
    }
    env.update(extra)
    return subprocess.run(
        ["bash", str(fake / "deploy/scripts/up.sh"), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )


def calls(fake: Path) -> list[list[str]]:
    return [json.loads(line) for line in (fake / "calls.jsonl").read_text().splitlines()]


def ups(fake: Path) -> list[list[str]]:
    return [args[1:] for args in calls(fake) if args[:2] == ["compose", "up"]]


def metadata(fake: Path) -> dict:
    return json.loads((fake / "config.json").read_text())["services"]


def test_default_jobs_then_residents_match_compose(fake: Path) -> None:
    result = run(fake)
    assert result.returncode == 0, result.stderr
    commands = ups(fake)
    specs = metadata(fake)
    default = {name for name, spec in specs.items() if not spec.get("profiles")}
    jobs = [args[-1] for args in commands[:-1]]
    assert jobs == ["migrate", "timescale-apply", "db-roles"]
    assert set(jobs) == {name for name in default if specs[name]["restart"] == "no"}
    for args in commands[:-1]:
        assert args == ["up", "--build", "--exit-code-from", args[-1], args[-1]]
    daemon = commands[-1]
    assert daemon[:8] == ["up", "-d", "--build", "--wait", "--wait-timeout", "19", "--no-deps", "postgres"]
    residents = daemon[7:]
    assert set(residents) == default - set(jobs)
    assert residents.index("postgres") < residents.index("api") < residents.index("nginx")
    assert calls(fake)[-1] == ["compose", "ps", "-a"]


@pytest.mark.parametrize("job", ["migrate", "timescale-apply", "db-roles"])
@pytest.mark.parametrize("rc", [1, 7])
def test_failed_job_stops_before_residents(fake: Path, job: str, rc: int) -> None:
    result = run(fake, FAKE_FAIL_JOB=job, FAKE_JOB_RC=str(rc))
    assert result.returncode == rc, result.stderr
    expected = ["migrate", "timescale-apply", "db-roles"]
    assert [args[-1] for args in ups(fake)] == expected[:expected.index(job) + 1]
    assert not any("--wait" in args for args in ups(fake))
    assert f"compose.sh logs {job}" in result.stderr
    assert ["compose", "ps", "-a"] not in calls(fake)


@pytest.mark.parametrize(("selected", "jobs", "residents"), [
    (["postgres"], [], {"postgres"}),
    (["redis", "postgres"], [], {"redis", "postgres"}),
    (["api"], ["migrate", "timescale-apply", "db-roles"], {"api", "postgres", "redis"}),
    (["nginx"], ["migrate", "timescale-apply", "db-roles"], {"api", "nginx", "postgres", "redis"}),
    (["migrate"], ["migrate"], {"postgres"}),
    (["timescale-apply"], ["migrate", "timescale-apply"], {"postgres"}),
    (["--no-deps", "api"], [], {"api"}),
    (["--no-deps=true", "api"], [], {"api"}),
    (["--no-deps", "--no-deps=false", "api"], ["migrate", "timescale-apply", "db-roles"], {"api", "postgres", "redis"}),
    (["--no-deps", "migrate"], ["migrate"], set()),
    (["--", "api", "api"], ["migrate", "timescale-apply", "db-roles"], {"api", "postgres", "redis"}),
])
def test_selected_services_and_dependencies(fake: Path, selected: list[str], jobs: list[str], residents: set[str]) -> None:
    result = run(fake, *selected)
    assert result.returncode == 0, result.stderr
    commands = ups(fake)
    assert [args[-1] for args in commands if "--exit-code-from" in args] == jobs
    daemon = [args for args in commands if "--wait" in args]
    assert len(daemon) == bool(residents)
    if residents:
        # --no-deps may be both supplied by the caller and added internally.
        last_no_deps = len(daemon[0]) - 1 - daemon[0][::-1].index("--no-deps")
        assert set(daemon[0][last_no_deps + 1:]) == residents


def test_options_keep_values_and_wait_only_for_residents(fake: Path) -> None:
    result = run(fake, "--pull", "never", "--timeout=23", "--wait-timeout", "51", "--scale", "api=2", "api")
    assert result.returncode == 0, result.stderr
    for args in ups(fake):
        assert args[args.index("--pull") + 1] == "never"
        assert "--timeout=23" in args
        if "--exit-code-from" in args:
            assert "--wait-timeout" not in args and "--scale" not in args
        else:
            assert args[args.index("--scale") + 1] == "api=2"
            assert args.count("--wait-timeout") == 2 and "51" in args


def test_option_value_that_is_service_name_is_not_selected(fake: Path) -> None:
    result = run(fake, "--no-attach", "redis", "postgres")
    assert result.returncode == 0, result.stderr
    assert ups(fake) == [[
        "up", "-d", "--build", "--wait", "--wait-timeout", "19",
        "--no-attach", "redis", "--no-deps", "postgres",
    ]]


@pytest.mark.parametrize("args", [["--build"], ["--pull"], ["--wait-timeout"]])
def test_missing_option_value_or_unknown_service_never_starts(fake: Path, args: list[str]) -> None:
    # --build has no value; add an unknown service to exercise planner validation.
    if args == ["--build"]:
        args += ["unknown-service"]
    result = run(fake, *args)
    assert result.returncode != 0
    assert ups(fake) == []


def test_skip_build_applies_to_both_phases(fake: Path) -> None:
    result = run(fake, AIA_UP_BUILD="0")
    assert result.returncode == 0, result.stderr
    assert all("--build" not in args for args in ups(fake))


def test_config_failure_does_not_start_even_with_valid_output(fake: Path) -> None:
    result = run(fake, FAKE_CONFIG_RC="9")
    assert result.returncode == 9
    assert ups(fake) == []


def test_service_listing_failure_does_not_start(fake: Path) -> None:
    result = run(fake, FAKE_SERVICES_RC="6")
    assert result.returncode == 6
    assert ups(fake) == []


def test_resident_failure_is_propagated(fake: Path) -> None:
    result = run(fake, FAKE_RESIDENT_RC="8")
    assert result.returncode == 8
    assert ["compose", "ps", "-a"] not in calls(fake)


def test_new_job_and_restart_changes_follow_config(fake: Path) -> None:
    specs = metadata(fake)
    specs["new-job"] = {"restart": "no", "depends_on": {"db-roles": {}}}
    specs["api"]["depends_on"]["new-job"] = {}
    specs["beat"]["restart"] = "no"
    # Reverse mapping order to prove dependency sorting, not YAML declaration order.
    (fake / "config.json").write_text(json.dumps({"services": dict(reversed(list(specs.items())))}))
    result = run(fake)
    assert result.returncode == 0, result.stderr
    jobs = [args[-1] for args in ups(fake) if "--exit-code-from" in args]
    assert jobs.index("migrate") < jobs.index("timescale-apply") < jobs.index("db-roles") < jobs.index("new-job")
    assert "beat" in jobs
    assert "new-job" not in ups(fake)[-1] and "beat" not in ups(fake)[-1]


def test_opt_in_profile_is_not_enabled_by_metadata_query(fake: Path) -> None:
    assert run(fake).returncode == 0
    disabled = {name for name, spec in metadata(fake).items() if spec.get("profiles")}
    assert all(not disabled.intersection(args) for args in ups(fake))


def test_explicit_profile_service_stays_selected(fake: Path) -> None:
    assert run(fake, "maint-cli").returncode == 0
    assert [args[-1] for args in ups(fake) if "--exit-code-from" in args] == ["maint-cli"]
    assert set(ups(fake)[-1][7:]) == {"postgres", "redis"}


def test_environment_profile_is_honored(fake: Path) -> None:
    assert run(fake, COMPOSE_PROFILES="maint").returncode == 0
    assert "maint-cli" in [args[-1] for args in ups(fake) if "--exit-code-from" in args]


def test_defaults_come_from_compose_not_shell_profiles(fake: Path) -> None:
    # Simulate a profile resolved by Compose from its env file without creating/reading one.
    assert run(fake, FAKE_DEFAULT_NAMES="maint-cli").returncode == 0
    assert [args[-1] for args in ups(fake) if "--exit-code-from" in args] == ["maint-cli"]
    assert set(ups(fake)[-1][7:]) == {"postgres", "redis"}
