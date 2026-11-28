"""0039 只读演练脚本的静态与假 psql 验收。"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "deploy/scripts/db-dryrun-0039.sh"

FAKE = r"""#!/bin/sh
s=$(cat)
printf '%s\n' "$s" >>"$FAKE_LOG"
printf 'argv=%s|PGHOST=%s|PGSERVICE=%s|PGPORT=%s\n' "$*" "${PGHOST-}" "${PGSERVICE-}" "${PGPORT-}" >>"$FAKE_LOG.argv"
case "$s" in
  *version_num*) printf '%s\n' "${FAKE_HEAD:-0038}" ;;
  *pg_extension*) printf '%s\n' 0 ;;
  *to_regclass*) printf '%s\n' 1 ;;
  *"SELECT column_name FROM information_schema.columns"*)
    case "$s" in
      *quotes_snapshot*) printf '%s\n' code ts source row_id revision content_fingerprint ;;
      *) printf '%s\n' code ts source source_licence_id row_id revision content_fingerprint is_final ;;
    esac ;;
  *"quotes_snapshot WHERE source IS NOT NULL"*) printf '%s\n' 1 ;;
  *market.*)
    t=$(printf '%s\n' "$s" | sed -n "s/.*market\.\([a-z0-9_]*\).*/\1/p" | sed -n '1p')
    bad=1; [ "${FAKE_HEAD-}" = 0039 ] && bad=0
    cat <<OUT
is_hypertable=false
chunks=0
compressed_chunks=0
primary_key=pk_x
unique_indexes=uq_x
rows=2
source.NULL=1
source.mairui=1
licence_null_rows=1
dup_code_ts_groups=1
dup_code_ts_rows=2
predict.$t.backfill_rows=2
predict.$t.mairui_null_licence=$bad
predict.$t.source_outside_scope=$bad
predict.$t.licence_relation_violation=$bad
predict.$t.conflict_legacy_groups=$bad
predict.$t.conflict_offline_groups=$bad
predict.$t.conflict_licence_groups=$bad
predict.$t.columns_already_present=$bad
post.$t.revision_gt_zero=0
post.$t.row_id_null=0
post.$t.conflict_fingerprint_licence=0
post.$t.conflict_fingerprint_offline=0
OUT
    ;;
  *) printf '%s\n' 0 ;;
esac
"""


@pytest.fixture
def fake(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    psql = bindir / "psql"
    psql.write_text(FAKE, encoding="utf-8")
    psql.chmod(0o755)
    return tmp_path


def run(fake: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        PATH=f"{fake / 'bin'}:{env['PATH']}",
        POSTGRES_USER="fake",
        POSTGRES_DB="fake",
        FAKE_LOG=str(fake / "sql.log"),
    )
    env.update(extra)
    return subprocess.run(
        ["sh", str(SCRIPT), *args],
        check=False,
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
    )


def test_static_and_shell_syntax() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(
        r"\b(?:ALTER|CREATE|DROP|INSERT|UPDATE|DELETE|TRUNCATE|COPY|GRANT)\b",
        text,
        re.IGNORECASE,
    )
    for shell in ("sh", "dash"):
        assert subprocess.run([shell, "-n", str(SCRIPT)], check=False).returncode == 0


def test_head_gate_and_already_applied(fake: Path) -> None:
    blocked = run(fake, "--pre", FAKE_HEAD="0037")
    assert blocked.returncode == 2
    assert "reason=unexpected_head:0037" in blocked.stdout
    done = run(fake, "--pre", FAKE_HEAD="0039")
    assert done.returncode == 0
    assert done.stdout.strip() == "dry_run_status=already_applied"


def test_pre_lists_all_reasons_and_keeps_read_only(fake: Path) -> None:
    result = run(fake, "--pre")
    assert result.returncode == 2
    for reason in (
        "mairui_null_licence",
        "source_outside_scope",
        "licence_relation_violation",
        "conflict_legacy_groups",
        "conflict_offline_groups",
        "conflict_licence_groups",
        "columns_already_present",
        "quotes_source_outside_scope",
    ):
        assert (
            f"reason=minute_bars:{reason}:" in result.stdout
            or f"reason=quotes_snapshot:{reason}:" in result.stdout
        )
    assert result.stdout.rstrip().endswith("dry_run_status=blocked")
    sql = (fake / "sql.log").read_text(encoding="utf-8")
    chunks = [part for part in sql.split("BEGIN READ ONLY;\n")[1:] if part]
    assert chunks and all(part.rstrip().endswith("ROLLBACK;") for part in chunks)
    assert not re.search(
        r"\b(?:ALTER|CREATE|DROP|INSERT|UPDATE|DELETE|TRUNCATE|COPY|GRANT)\b",
        sql,
        re.IGNORECASE,
    )


def test_post_accepts_crlf_baseline_and_hides_connection_data(
    fake: Path, tmp_path: Path
) -> None:
    baseline = tmp_path / "pre.txt"
    lines = [
        "table.quotes_snapshot.rows=2",
        "table.quotes_snapshot.licence_null_rows=1",
        "table.realtime_quotes.rows=2",
        "table.realtime_quotes.licence_null_rows=1",
        "table.minute_bars.rows=2",
        "table.minute_bars.licence_null_rows=1",
        "table.minute5_bars.rows=2",
        "table.minute5_bars.licence_null_rows=1",
    ]
    baseline.write_bytes(("\r\n".join(lines) + "\r\n").encode())
    result = run(fake, "--post", str(baseline), FAKE_HEAD="0039")
    assert result.returncode == 0
    assert "://" not in result.stdout and "password" not in result.stdout.lower()


def test_post_blocks_on_row_drift_without_suggesting_delete(
    fake: Path, tmp_path: Path
) -> None:
    baseline = tmp_path / "pre.txt"
    tables = ("quotes_snapshot", "realtime_quotes", "minute_bars", "minute5_bars")
    lines = [f"table.{t}.rows=3\ntable.{t}.licence_null_rows=1" for t in tables]
    baseline.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = run(fake, "--post", str(baseline), FAKE_HEAD="0039")
    assert result.returncode == 2
    assert "reason=minute_bars:rows_changed:3->2" in result.stdout
    assert "delete" not in result.stdout.lower() and "删除" not in result.stdout


def _baseline(tmp_path: Path) -> Path:
    baseline = tmp_path / "pre.txt"
    lines = []
    for t in ("quotes_snapshot", "realtime_quotes", "minute_bars", "minute5_bars"):
        lines += [f"table.{t}.rows=2", f"table.{t}.licence_null_rows=1"]
    baseline.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return baseline


def test_post_accepts_dbname_and_pins_local_socket(fake: Path, tmp_path: Path) -> None:
    result = run(
        fake,
        "--post",
        str(_baseline(tmp_path)),
        "--dbname",
        "aia",
        FAKE_HEAD="0039",
        PGHOST="external.example",
        PGSERVICE="evil",
        PGPORT="6543",
    )
    assert result.returncode == 0, result.stderr
    calls = (fake / "sql.log.argv").read_text(encoding="utf-8").splitlines()
    assert calls
    for call in calls:
        assert "-h /var/run/postgresql" in call and "-d aia" in call
        assert "PGHOST=/var/run/postgresql|PGSERVICE=|PGPORT=" in call
        assert "external.example" not in call


@pytest.mark.parametrize(
    "args",
    [
        ("--pre", "--dbname", "safe -h external.example"),
        ("--pre", "--dbname=-hexternal"),
        ("--pre", "--dbname", "postgresql://x@external/aia"),
        ("--pre", "--dbname", ""),
        ("--pre", "--dbname"),
        ("--pre", "extra"),
        ("--post",),
        ("--post", "-", "--dbname", "aia", "extra"),
    ],
)
def test_rejects_unsafe_or_malformed_args_before_connecting(
    fake: Path, args: tuple[str, ...]
) -> None:
    result = run(fake, *args)
    assert result.returncode == 4
    assert not (fake / "sql.log.argv").exists()


def test_rejects_unsafe_env_names_before_connecting(fake: Path) -> None:
    result = run(fake, "--pre", POSTGRES_DB="aia -h external.example")
    assert result.returncode == 4
    assert not (fake / "sql.log.argv").exists()
