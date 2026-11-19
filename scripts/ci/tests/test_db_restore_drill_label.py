"""使用合成命令替身验证恢复演练的目标身份和入口拒绝。"""

from pathlib import Path
import shutil
import subprocess
import tempfile
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


DOCKER_FIXTURE = r'''
case "$1" in
    info)
        echo docker-info >> "$FIXTURE_CALLS"
        ;;
    run)
        [ "$5" = --label ] && [[ "$6" == aia.drill=* ]] || exit 90
        printf '%s\n' "${6#aia.drill=}" > "$FIXTURE_LABEL"
        ;;
    exec)
        if [ "${3:-}" = pg_isready ]; then
            exit 0
        fi
        if [[ "${5:-}" == aia-drill-src-* && "${8:-}" == 'exec psql '* && ! -f "$FIXTURE_TARGET_INSPECTED" ]]; then
            # The source setup gets an empty synthetic response from Docker itself.
            echo source-sql-fixture >> "$FIXTURE_CALLS"
            exit 0
        fi
        echo sql >> "$FIXTURE_CALLS"
        exit 91
        ;;
    inspect)
        [ "$#" -eq 4 ] && [ "$2" = --format ] || exit 90
        label=$(<"$FIXTURE_LABEL")
        case "$4" in
            aia-drill-src-*)
                [ "$3" = '{{ index .Config.Labels "aia.drill" }}' ] || exit 90
                printf '%s\n' "$label"
                ;;
            aia-drill-dst-*)
                [ "$3" = '{{ index .Config.Labels "aia.drill" }}|{{ .Config.Image }}' ] || exit 90
                echo target-inspect >> "$FIXTURE_CALLS"
                : > "$FIXTURE_TARGET_INSPECTED"
                case "$FIXTURE_CASE" in
                    label) printf 'different-drill|%s\n' "$AIA_PG_IMAGE" ;;
                    image) printf '%s|fixture-postgres:other\n' "$label" ;;
                    inspect) exit 7 ;;
                    *) exit 90 ;;
                esac
                ;;
            *) exit 90 ;;
        esac
        ;;
    *) exit 90 ;;
esac
'''


class TestDrillEntrypoint(unittest.TestCase):
    def assert_entrypoint_refused(self, scenario: str, reason: str) -> None:
        system_path = "/usr/bin:/bin"
        bash = shutil.which("bash", path=system_path)
        self.assertIsNotNone(bash)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "deploy/scripts"
            (scripts / "lib").mkdir(parents=True)
            entrypoint = scripts / SCRIPT.name
            shutil.copyfile(SCRIPT, entrypoint)
            shutil.copyfile(SCRIPT.parent / "lib/common.sh", scripts / "lib/common.sh")

            sql_dir = root / "deploy/db/drill"
            sql_dir.mkdir(parents=True)
            for name in ("sample-schema.sql", "sample-data.sql", "metrics.sql"):
                (sql_dir / name).touch()
            work = root / "work"
            work.mkdir()
            dump = work / "fixture.dump"
            dump.write_bytes(b"synthetic drill fixture\n")
            calls = root / "calls.log"
            calls.touch()

            bin_dir = root / "bin"
            bin_dir.mkdir()
            for name in ("base64", "cut", "date", "dirname", "grep", "head", "mkdir", "seq", "sha256sum", "stat", "tail", "tr"):
                tool = shutil.which(name, path=system_path)
                self.assertIsNotNone(tool, name)
                (bin_dir / name).symlink_to(tool)

            replacements = {
                bin_dir / "docker": DOCKER_FIXTURE,
                bin_dir / "psql": 'echo sql >> "$FIXTURE_CALLS"; exit 91',
                bin_dir / "mktemp": 'printf "%s\\n" "$FIXTURE_WORK"',
                scripts / "db-apply-timescale.sh": 'printf "NOTICE: [aia-ts] fixture OK\\n"',
                scripts / "db-backup.sh": 'printf "%s\\n" "$FIXTURE_DUMP"',
                scripts / "db-restore.sh": 'echo restore >> "$FIXTURE_CALLS"; exit 91',
            }
            for path, content in replacements.items():
                path.write_text(f"#!{bash}\nset -euo pipefail\n{content}\n", encoding="utf-8")
                path.chmod(0o755)

            # A fresh environment and allowlisted PATH keep all service calls in the fixture.
            env = {
                "PATH": str(bin_dir),
                "LC_ALL": "C.UTF-8",
                "AIA_PG_IMAGE": "fixture-postgres:fixed",
                "AIA_DRILL_KEEP": "1",
                "FIXTURE_CASE": scenario,
                "FIXTURE_CALLS": str(calls),
                "FIXTURE_LABEL": str(root / "label"),
                "FIXTURE_TARGET_INSPECTED": str(root / "target-inspected"),
                "FIXTURE_WORK": str(work),
                "FIXTURE_DUMP": str(dump),
            }
            if scenario == "direct":
                env["AIA_PSQL_MODE"] = "direct"
            result = subprocess.run(
                [bash, str(entrypoint)], cwd=root, env=env, capture_output=True,
                encoding="utf-8", timeout=10,
            )
            events = calls.read_text(encoding="utf-8").splitlines()
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn(reason, result.stderr)
            self.assertEqual(events.count("restore"), 0, events)
            self.assertEqual(events.count("sql"), 0, events)
            if scenario == "direct":
                self.assertEqual(events, [])
            else:
                self.assertIn("source-sql-fixture", events)
                self.assertEqual(events.count("target-inspect"), 1, events)

    def test_public_entrypoint_refuses_wrong_label(self) -> None:
        self.assert_entrypoint_refused("label", "的 aia.drill 标签与本次演练不符")

    def test_public_entrypoint_refuses_wrong_image(self) -> None:
        self.assert_entrypoint_refused("image", "的镜像与演练镜像不符")

    def test_public_entrypoint_refuses_failed_target_inspect(self) -> None:
        self.assert_entrypoint_refused("inspect", "拒绝恢复：无法 inspect 目标容器")

    def test_public_entrypoint_refuses_direct_mode(self) -> None:
        self.assert_entrypoint_refused("direct", "恢复演练禁止直连")


if __name__ == "__main__":
    unittest.main()
