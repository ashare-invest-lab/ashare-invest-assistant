"""Coverage combine must never hide a bad shard behind healthy shards."""
import os
import shlex
import subprocess
import sys

import pytest
import yaml

from conftest import CI_DIR, REPO

CoverageData = pytest.importorskip("coverage").CoverageData


def coverage_shards(tmp_path):
    paths = []
    for i in range(1, 7):
        directory = tmp_path / "shards" / f"artifact-{i}"
        directory.mkdir(parents=True)
        path = directory / f"coverage-shard-{i}.data"
        data = CoverageData(basename=str(path))
        data.add_lines({"synthetic.py": {i}})
        data.write()
        paths.append(path)
    return paths


def damage(path, invalid):
    if invalid == "corrupt":
        path.write_bytes(b"not a coverage database")
    elif invalid == "empty":
        path.write_bytes(b"")
    elif invalid == "truncated":
        path.write_bytes(path.read_bytes()[:100])
    elif invalid == "missing":
        path.unlink()
    else:
        path.unlink()
        data = CoverageData(basename=str(path))
        if invalid == "no-measured-files":
            data.add_lines({})
        else:
            data.add_lines({"synthetic.py": set()})
        data.write()
        assert path.stat().st_size > 0
        if invalid == "no-measured-files":
            check = CoverageData(basename=str(path))
            check.read()
            assert not check.measured_files()


@pytest.mark.parametrize("invalid", [None, "corrupt", "empty", "truncated", "missing",
                                     "no-measured-files", "no-measured-lines"])
def test_coverage_data_cli(tmp_path, invalid):
    paths = coverage_shards(tmp_path)
    if invalid:
        damage(paths[-1], invalid)
    result = subprocess.run([sys.executable, str(CI_DIR / "check_coverage_data.py"), *map(str, paths)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == (1 if invalid else 0), result.stdout + result.stderr
    if invalid:
        assert str(paths[-1]) in result.stdout
        assert "::error title=coverage data::" in result.stdout


@pytest.mark.parametrize("invalid", ["corrupt", "empty"])
def test_workflow_stops_before_combine_for_bad_coverage(tmp_path, invalid):
    paths = coverage_shards(tmp_path)
    damage(paths[-1], invalid)
    python = tmp_path / "src/backend/.venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    python.chmod(0o755)
    (tmp_path / "scripts").symlink_to(REPO / "scripts", target_is_directory=True)
    jobs = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text())["jobs"]
    command = next(step["run"] for step in jobs["backend"]["steps"]
                   if step.get("name") == "合并覆盖率与 JUnit")
    result = subprocess.run(["bash", "-c", command], cwd=tmp_path,
                            env={**os.environ, "RUNNER_TEMP": str(tmp_path)},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error title=coverage data::" in result.stdout
    assert not (tmp_path / ".coverage").exists()
