"""T-O103：只用 Bash 和桩函数验证演练边界，不调用 Docker、不连接数据库。"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "deploy/scripts/db-restore-drill.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")
PSQL_IN = "psql_in() {" + TEXT.split("psql_in() {", 1)[1].split("\nmetrics()", 1)[0]
ENV = {"PATH": "/usr/bin:/bin"}
DIE = 'aia_die() { printf "ERROR: %s\\n" "$*" >&2; exit 1; }\n'


def _psql(db: str, *args: str, label: str = "run-test", inspect_rc: str = "0",
          container: str = "drill-src") -> subprocess.CompletedProcess[str]:
    stubs = r"""
RUN_ID=run-test
SRC=drill-src
aia_docker() {
  [ "$#" -eq 4 ] && [ "$1" = inspect ] && [ "$2" = --format ] \
    && [ "$3" = '{{ index .Config.Labels "aia.drill" }}' ] && [ "$4" = "$TARGET" ] || exit 99
  echo INSPECT >&2
  printf '%s\n' "$LABEL"
  return "$INSPECT_RC"
}
aia_psql() { printf 'PSQL\n'; printf '%s\n' "$@"; }
"""
    return subprocess.run(
        ["bash", "-euc", DIE + stubs + PSQL_IN + '\npsql_in "$@"', "test", container, db, *args],
        env={**ENV, "LABEL": label, "INSPECT_RC": inspect_rc, "TARGET": container},
        capture_output=True, text=True, timeout=5,
    )


class RestoreDrillTest(unittest.TestCase):
    def test_bash_syntax(self) -> None:
        subprocess.run(["bash", "-n", str(SCRIPT)], check=True, env=ENV)

    def test_unsafe_environment_rejected_first(self) -> None:
        cases = [{"AIA_PSQL_MODE": "direct"}]
        cases += [{name: value} for name in ("PGHOST", "PGPORT", "PGDATABASE") for value in ("", "test")]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # 隔离完整入口；common 桩仅提供 aia_die，意外继续执行也不会调用 Docker。
            script = root / SCRIPT.name
            script.write_text(TEXT, encoding="utf-8")
            (root / "lib").mkdir()
            (root / "lib/common.sh").write_text(DIE, encoding="utf-8")
            for extra in cases:
                with self.subTest(extra=extra):
                    result = subprocess.run(["bash", str(script)], env={**ENV, **extra},
                                            capture_output=True, text=True, timeout=5)
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("ERROR: 恢复演练禁止直连", result.stderr)
                    self.assertNotIn("command not found", result.stderr)
                    self.assertEqual(sorted(p.name for p in root.iterdir()), [SCRIPT.name, "lib"])

    def test_missing_wrong_or_unreadable_label_rejected(self) -> None:
        for label, rc in [("", "0"), ("<no value>", "0"), ("another-run", "0"), ("run-test", "1")]:
            with self.subTest(label=label, rc=rc):
                result = _psql("aia_drill", "-c", "SELECT 1", label=label, inspect_rc=rc)
                self.assertEqual(result.returncode, 1)
                self.assertIn("ERROR:", result.stderr)
                self.assertIn("INSPECT", result.stderr)
                self.assertNotIn("PSQL", result.stdout)

    def test_non_drill_database_or_postgres_misuse_rejected(self) -> None:
        cases = [
            ("aia", ("-c", "SELECT 1"), "drill-src"),
            ("template1", ("-c", "SELECT 1"), "drill-src"),
            ("postgres", (), "drill-src"),
            ("postgres", ("-c", "SELECT 1"), "drill-src"),
            ("postgres", ("-c", "CREATE DATABASE aia"), "drill-src"),
            ("postgres", ("-c", "CREATE DATABASE aia_drill", "-c", "SELECT 1"), "drill-src"),
            ("postgres", ("-c", "CREATE DATABASE aia_drill"), "drill-dst"),
        ]
        for db, args, container in cases:
            with self.subTest(db=db, args=args, container=container):
                result = _psql(db, *args, container=container)
                self.assertEqual(result.returncode, 1)
                self.assertIn("ERROR:", result.stderr)
                self.assertNotIn("PSQL", result.stdout)

    def test_labeled_drill_targets_and_exact_create_allowed(self) -> None:
        cases = [
            ("aia_drill", ("-tA", "-c", "SELECT 1"), "drill-src"),
            ("aia_drill_restored", ("-qtA", "-c", "SELECT 1"), "drill-dst"),
            ("postgres", ("-c", "CREATE DATABASE aia_drill"), "drill-src"),
        ]
        for db, args, container in cases:
            with self.subTest(db=db, container=container):
                result = _psql(db, *args, container=container)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "INSPECT\n")
                self.assertEqual(result.stdout.splitlines(), ["PSQL", container, db, "-q", *args])

    def test_all_psql_calls_use_guard(self) -> None:
        self.assertEqual(TEXT.count("aia_psql "), 1)
        self.assertIn('SRC_VER="$(psql_in ', TEXT)
        self.assertIn('DST_VER="$(psql_in ', TEXT)


if __name__ == "__main__":
    unittest.main()
