"""使用合成命令替身验证恢复演练的目标身份和入口拒绝。"""

import json
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path


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
role_for_id() {
    case "$1" in
        fixture-source) printf 'source\n' ;;
        fixture-target) printf 'target\n' ;;
        *) record unexpected-container; exit 90 ;;
    esac
}

case "$1" in
    info) record docker-info ;;
    create)
        [ "$2" = --name ] && [ "$4" = --label ] && [[ "$5" == aia.drill=* ]] || exit 90
        [ "${19}" = postgres ] || exit 90
        case "$3" in
            aia-drill-src-*) role=source ;;
            aia-drill-dst-*) role=target ;;
            *) exit 90 ;;
        esac
        printf '%s\n' "${5#aia.drill=}" > "$FIXTURE_WORK/$role.label"
        printf '%s\n' "${18}" > "$FIXTURE_WORK/$role.image"
        record "$role-create"
        printf 'fixture-%s\n' "$role"
        ;;
    start)
        role=$(role_for_id "$2")
        [ -f "$FIXTURE_WORK/$role.label" ] || exit 90
        record "$role-start"
        : > "$FIXTURE_WORK/$role.started"
        ;;
    exec)
        if [ "${3:-}" = pg_isready ]; then
            role=$(role_for_id "$2")
            [ -f "$FIXTURE_WORK/$role.started" ]
            exit
        fi
        role=$(role_for_id "${5:-}")
        record "$role-sql"
        [ "$FIXTURE_CASE" = success ] || exit 91
        [ -f "$FIXTURE_WORK/$role.started" ] && [[ "$8" == 'exec psql '* ]] || exit 90
        case "${11:-}" in
            -tA)
                case "$(< /dev/stdin)" in
                    fixture-metrics)
                        printf '%s\n' 'chunks.compressed=2' 'chunks.compressed.minute_bars=1' \
                            'jobs.count=9' 'rows.market.minute_bars=12' 'jobs=fixture'
                        ;;
                    *minute_bars.before_bytes*)
                        printf '%s\n' 'minute_bars.before_bytes=24' 'minute_bars.after_bytes=12'
                        ;;
                    *cagg.refresh_after_restore*) printf 'cagg.refresh_after_restore=ok\n' ;;
                    *) exit 90 ;;
                esac
                ;;
            -qtA) printf '17 / timescaledb fixture\n' ;;
            -c|-v|'') ;;
            *) exit 90 ;;
        esac
        ;;
    inspect)
        [ "$#" -eq 4 ] && [ "$2" = --format ] || exit 90
        role=$(role_for_id "$4")
        label=$(<"$FIXTURE_WORK/$role.label")
        case "$3" in
            '{{ index .Config.Labels "aia.drill" }}') printf '%s\n' "$label" ;;
            '{{ index .Config.Labels "aia.drill" }}|{{ .Config.Image }}')
                [ "$role" = target ] || exit 90
                image=$(<"$FIXTURE_WORK/$role.image")
                record target-inspect
                case "$FIXTURE_CASE" in
                    label) printf 'different-drill|%s\n' "$image" ;;
                    image) printf '%s|fixture-postgres:other\n' "$label" ;;
                    inspect) exit 7 ;;
                    success) printf '%s|%s\n' "$label" "$image" ;;
                    *) exit 90 ;;
                esac
                ;;
            *) exit 90 ;;
        esac
        ;;
    rm)
        [ "$#" -eq 3 ] && [ "$2" = -fv ] || exit 90
        role=$(role_for_id "$3")
        [ -f "$FIXTURE_WORK/$role.label" ] || exit 90
        record "$role-remove"
        ;;
    *) record unexpected-docker; exit 90 ;;
esac
'''


class TestDrillEntrypoint(unittest.TestCase):
    def run_entrypoint(self, scenario: str) -> tuple[subprocess.CompletedProcess[str], list[str], dict | None]:
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
            for name in ("sample-schema.sql", "sample-data.sql"):
                (sql_dir / name).touch()
            (sql_dir / "metrics.sql").write_text("fixture-metrics\n", encoding="utf-8")
            work = root / "work"
            work.mkdir()
            calls = root / "calls.log"
            calls.touch()

            bin_dir = root / "bin"
            bin_dir.mkdir()
            for name in (
                "awk", "base64", "cat", "cut", "date", "dirname", "grep", "head", "mkdir", "numfmt",
                "python3", "sed", "seq", "sha256sum", "stat", "tail", "tr",
            ):
                tool = shutil.which(name, path=system_path)
                self.assertIsNotNone(tool, name)
                (bin_dir / name).symlink_to(tool)

            # Both source helpers send queries in the real drill. Count their attempted
            # invocations as source SQL requests before returning any fixture data.
            replacements = {
                bin_dir / "docker": DOCKER_FIXTURE,
                bin_dir / "psql": "record direct-sql; exit 91",
                bin_dir / "mktemp": 'printf "%s\\n" "$FIXTURE_WORK"',
                bin_dir / "rm": '[ "$#" -eq 2 ] && [ "$1" = -rf ] && [ "$2" = "$FIXTURE_WORK" ]',
                scripts / "db-apply-timescale.sh": r'''
record source-sql
record apply
[ "$FIXTURE_CASE" = success ] && [ "$*" = '--container fixture-source --db aia_drill' ] || exit 91
printf 'NOTICE: [aia-ts] fixture OK\n'
''',
                scripts / "db-backup.sh": r'''
record source-sql
record backup
[ "$FIXTURE_CASE" = success ] && [ "$*" = "--container fixture-source --db aia_drill --out-dir $FIXTURE_WORK" ] || exit 91
printf 'synthetic drill fixture\n' > "$FIXTURE_WORK/fixture.dump"
printf '%s/fixture.dump\n' "$FIXTURE_WORK"
''',
                scripts / "db-restore.sh": r'''
record restore
[ "$FIXTURE_CASE" = success ] && [ "$*" = "$FIXTURE_WORK/fixture.dump --container fixture-target --db aia_drill_restored" ] || exit 91
''',
            }
            for path, content in replacements.items():
                path.write_text(
                    f"#!{bash}\nset -euo pipefail\n"
                    'record() { printf "%s\\n" "$1" >> "$FIXTURE_CALLS"; }\n'
                    f"{content}\n",
                    encoding="utf-8",
                )
                path.chmod(0o755)

            # A fresh environment and allowlisted PATH keep all service calls in the fixture.
            env = {
                "PATH": str(bin_dir),
                "LC_ALL": "C.UTF-8",
                "AIA_PG_IMAGE": "fixture-postgres:fixed",
                "FIXTURE_CASE": scenario,
                "FIXTURE_CALLS": str(calls),
                "FIXTURE_WORK": str(work),
            }
            if scenario == "direct":
                env["AIA_PSQL_MODE"] = "direct"
            result = subprocess.run(
                [bash, str(entrypoint)], cwd=root, env=env, capture_output=True,
                encoding="utf-8", timeout=10,
            )
            events = calls.read_text(encoding="utf-8").splitlines()
            reports = list(root.glob("deploy/drills/*-restore-drill.json"))
            self.assertLessEqual(len(reports), 1)
            report = json.loads(reports[0].read_text(encoding="utf-8")) if reports else None
            return result, events, report

    def assert_entrypoint_refused(self, scenario: str, reason: str) -> None:
        result, events, report = self.run_entrypoint(scenario)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        counts = Counter(events)
        for call in ("source-sql", "target-sql", "direct-sql", "restore"):
            self.assertEqual(counts[call], 0, (call, events))
        self.assertIn(reason, result.stderr)
        if scenario == "direct":
            self.assertEqual(events, [])
            self.assertIsNone(report)
        else:
            container_events = [event for event in events if event != "docker-info"]
            self.assertEqual(container_events, ["target-create", "target-inspect", "target-remove"])
            self.assertIsNotNone(report)
            self.assertEqual(report["failed_step"], "prepare-target")

    def test_public_entrypoint_refuses_wrong_label(self) -> None:
        self.assert_entrypoint_refused("label", "的 aia.drill 标签与本次演练不符")

    def test_public_entrypoint_refuses_wrong_image(self) -> None:
        self.assert_entrypoint_refused("image", "的镜像与演练镜像不符")

    def test_public_entrypoint_refuses_failed_target_inspect(self) -> None:
        self.assert_entrypoint_refused("inspect", "拒绝恢复：无法 inspect 目标容器")

    def test_public_entrypoint_refuses_direct_mode(self) -> None:
        self.assert_entrypoint_refused("direct", "恢复演练禁止直连")

    def test_public_entrypoint_runs_with_verified_identity(self) -> None:
        result, events, report = self.run_entrypoint("success")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIsNotNone(report)
        self.assertEqual(report["result"], "PASS")
        self.assertEqual(report["source"]["db"], "aia_drill")
        self.assertEqual(report["target"]["db"], "aia_drill_restored")
        counts = Counter(events)
        self.assertEqual(counts["target-inspect"], 2, events)
        self.assertEqual(counts["apply"], 2, events)
        self.assertEqual(counts["backup"], 1, events)
        self.assertEqual(counts["restore"], 1, events)
        self.assertEqual(counts["direct-sql"], 0, events)
        self.assertLess(events.index("target-inspect"), events.index("source-start"))
        self.assertLess(events.index("source-start"), events.index("source-sql"))
        self.assertLess(events.index("backup"), events.index("target-start"))
        restore = events.index("restore")
        self.assertGreater(restore, events.index("target-start"))
        self.assertEqual(events[restore - 1], "target-inspect")
        self.assertLess(restore, events.index("target-sql"))
        self.assertEqual(events[-2:], ["source-remove", "target-remove"])


if __name__ == "__main__":
    unittest.main()
