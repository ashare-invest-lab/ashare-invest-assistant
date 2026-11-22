"""资源采样脚本的假 Docker 验收。"""

from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path

from conftest import REPO

SCRIPT = REPO / "deploy/scripts/resource-sample.sh"


def fake_docker(tmp_path: Path) -> Path:
    state = tmp_path / "次数"
    state.write_text("0", encoding="utf-8")
    docker = tmp_path / "假docker"
    docker.write_text(
        """#!/bin/sh
if [ "$1" = ps ]; then
  printf '%s\\n' c1 c2
  exit 0
fi
if [ "$1" = stats ]; then
  n=$(cat "$FAKE_DOCKER_STATE")
  if [ "$n" = 0 ]; then
    printf 'api-1\\t10.00%%\\t100MiB / 1GiB\\t20.00%%\\t3\\n'
    printf 'worker-1\\t3.00%%\\t50MiB / 1GiB\\t5.00%%\\t2\\n'
  else
    printf 'api-1\\t12.00%%\\t120MiB / 1GiB\\t25.00%%\\t3\\n'
    printf 'worker-1\\t2.00%%\\t55MiB / 1GiB\\t6.00%%\\t2\\n'
  fi
  printf '%s' $((n + 1)) > "$FAKE_DOCKER_STATE"
  exit 0
fi
exit 1
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return docker


def test_csv_rows_project_filter_and_peaks(tmp_path: Path) -> None:
    docker = fake_docker(tmp_path)
    output = tmp_path / "采样.csv"
    env = {**os.environ, "AIA_DOCKER": str(docker), "FAKE_DOCKER_STATE": str(tmp_path / "次数")}
    result = subprocess.run(
        [str(SCRIPT), "--samples", "2", "--interval", "0", "--project", "aia", "--out", str(output)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    rows = list(csv.reader(output.read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["ts", "container", "cpu_pct", "mem_usage", "mem_limit", "mem_pct", "pids"]
    assert len(rows) == 1 + 2 * 2
    assert {row[1] for row in rows[1:]} == {"api-1", "worker-1"}
    assert all(row[4] == "1GiB" for row in rows[1:])
    assert "汇总 容器=api-1 cpu_pct峰值=12.00% mem_pct峰值=25.00%" in result.stdout
    assert "汇总 容器=worker-1 cpu_pct峰值=3.00% mem_pct峰值=6.00%" in result.stdout


def test_zero_samples_writes_header(tmp_path: Path) -> None:
    docker = fake_docker(tmp_path)
    output = tmp_path / "空.csv"
    env = {**os.environ, "AIA_DOCKER": str(docker), "FAKE_DOCKER_STATE": str(tmp_path / "次数")}
    result = subprocess.run(
        [str(SCRIPT), "--samples", "0", "--interval", "0", "--out", str(output)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    assert output.read_text(encoding="utf-8").splitlines() == ["ts,container,cpu_pct,mem_usage,mem_limit,mem_pct,pids"]
