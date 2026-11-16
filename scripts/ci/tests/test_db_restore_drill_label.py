"""恢复演练目标身份反控：仅运行摘取函数与桩，不访问 Docker 或数据库。"""

from pathlib import Path
import subprocess
import unittest


SCRIPT = Path(__file__).resolve().parents[3] / "deploy/scripts/db-restore-drill.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")
FUNCTION = "assert_drill_container() {" + TEXT.split(
    "assert_drill_container() {", 1
)[1].split("\n}", 1)[0] + "\n}"


class TestDrillContainer(unittest.TestCase):
    def run_check(self, label="drill-test", image="test-image:fixed", inspect_rc=0):
        stub = r'''
set -euo pipefail
RUN_ID=drill-test
IMAGE=test-image:fixed
aia_die() { printf '%s\n' "$*" >&2; exit 1; }
aia_docker() {
  [ "$#" -eq 4 ] && [ "$1" = inspect ] && [ "$2" = --format ] &&
    [ "$3" = '{{ index .Config.Labels "aia.drill" }}|{{ .Config.Image }}' ] &&
    [ "$4" = drill-target ] || exit 90
  printf '%s|%s\n' "$TEST_LABEL" "$TEST_IMAGE"
  return "$TEST_INSPECT_RC"
}
'''
        return subprocess.run(
            ["bash", "-c", stub + FUNCTION + '\nassert_drill_container "drill-target"'],
            env={"TEST_LABEL": label, "TEST_IMAGE": image, "TEST_INSPECT_RC": str(inspect_rc)},
            capture_output=True, text=True, timeout=10,
        )

    def assert_refused(self, **kwargs):
        result = self.run_check(**kwargs)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("拒绝恢复", result.stderr)

    def test_matching_identity(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_label(self):
        self.assert_refused(label="other-run")

    def test_wrong_image(self):
        self.assert_refused(image="other-image:fixed")

    def test_inspect_failure(self):
        self.assert_refused(inspect_rc=7)

    def test_empty_label(self):
        self.assert_refused(label="")

    def test_assert_before_restore_in_same_step(self):
        restore = TEXT.split('step "restore"\n', 1)[1].split("\ndone_step", 1)[0]
        call = 'assert_drill_container "$DST"'
        command = '"$AIA_ROOT/deploy/scripts/db-restore.sh" "$DUMP" --container "$DST" --db "$DST_DB"'
        self.assertIn(call, restore)
        self.assertLess(restore.index(call), restore.index(command))
        self.assertNotIn('\nstep "', restore)

    def test_bash_syntax(self):
        result = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
