"""T-B143w 全部输入为虚构数据；没有本机 initdb/pg_ctl 则 PG 未实跑。

不使用共享 pg_url/AIA_TEST_DATABASE_URL，避免误连任何用户数据库。
"""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

import psycopg
import pytest

from app.cli import tb143_reconcile_load as loader
from app.cli.tb143_export import DAY_COLUMNS
from app.cli.tb143_inputs import prepare
from app.ingest.tdx_local import DAY_LAYOUT, ExistingBar


class MemoryRepository:
    """按同样事务边界回滚的替身；不替代真实 SQL 验收。"""

    def __init__(self):
        self.rows = {}
        self.writes = 0
        self.reads = 0
        self.fail = False
        self.change_mairui = False
        self.out = None
        self.transaction_modes = []

    @contextmanager
    def transaction(self, apply):
        before = copy.deepcopy(self.rows)
        self.transaction_modes.append(apply)
        try:
            yield
        except BaseException:
            self.rows = before
            raise

    def securities(self):
        return {
            "000001.SZ": ("stock", "listed"),
            "000002.SZ": ("stock", "listed"),
            "920001.BJ": ("stock", "listed"),
            "920002.BJ": ("stock", "listed"),
            "920003.BJ": ("stock", "listed"),
            "510001.SH": ("etf", "listed"),
        }

    def existing(self, keys):
        self.reads += 1
        return {key: self.rows[key] for key in keys if key in self.rows}

    def counts(self, keys):
        return {
            "total": len(self.rows),
            "mairui": sum(r.source == "mairui" for r in self.rows.values()),
            "tdx_local": sum(r.source == "tdx_local" for r in self.rows.values()),
            "batch_keys": sum(k in self.rows for k in keys),
        }

    def insert(self, rows):
        self.writes += 1
        # 首次写库前，两份审计清单必须已完整关闭并可读。
        assert self.out is not None
        assert list(self.out.glob("*_new_keys.csv"))
        latest = sorted(self.out.glob("*_candidates.csv"))[-1]
        with latest.open() as stream:
            assert len(list(csv.DictReader(stream))) > 0
        inserted = 0
        for row in rows:
            key = row[:3]
            if key not in self.rows:
                self.rows[key] = ExistingBar("tdx_local", *row[3:])
                inserted += 1
        if self.change_mairui:
            self.rows[("000002.SZ", date(2001, 1, 1), "none")] = old("mairui")
        if self.fail:
            raise psycopg.DataError("synthetic failure; must not be printed")
        return inserted

    def close(self):
        pass


def old(source="mairui", price="10", amount="1000"):
    return ExistingBar(
        source, *(Decimal(price) for _ in range(4)), Decimal(100), Decimal(amount)
    )


def row(code="000001.SZ", day="2001-01-02", price="10", **changes):
    result = dict(
        zip(DAY_COLUMNS, (code, day, "none", price, price, price, price, "100", "1000"))
    )
    result.update(changes)
    return result


def write_csv(path, rows, columns=DAY_COLUMNS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def inputs(tmp_path, history=None, bj=None):
    history = [row()] if history is None else history
    bj = [row("920001.BJ", "2031-01-02")] if bj is None else bj
    write_csv(tmp_path / "history/day_2001.csv", history)
    write_csv(tmp_path / "bj/day_2031.csv", bj)
    codes = tmp_path / "codes.txt"
    codes.write_text("920001.BJ\n920002.BJ\n", encoding="utf-8")
    return [
        "--shards-dir",
        str(tmp_path / "history"),
        "--bj-codes",
        str(codes),
        "--bj-data",
        str(tmp_path / "bj"),
        "--out",
        str(tmp_path / "out"),
    ]


def invoke(tmp_path, args, repo, extra=()):
    repo.out = tmp_path / "out"
    result = loader.main([*args, *extra], factory=lambda _: repo)
    return result, json.loads((repo.out / "summary.json").read_text())


@pytest.mark.parametrize("apply", [False, True])
def test_classification_and_existing_rows_unchanged(tmp_path, apply):
    args = inputs(
        tmp_path,
        history=[
            row(day="2001-01-02"),
            row(day="2001-01-03"),
            row(day="2001-01-04"),
            row("510001.SH"),
            row(day="2001-02-30"),
            row(day="2001-01-05", adj_type="qfq"),
            row(day="2031-01-01"),
        ],
    )
    repo = MemoryRepository()
    repo.rows[("000001.SZ", date(2001, 1, 3), "none")] = old(
        "tdx_local", amount="1000.5"
    )
    repo.rows[("000001.SZ", date(2001, 1, 4), "none")] = old("mairui", price="11")
    original = copy.deepcopy(repo.rows)
    result, summary = invoke(
        tmp_path, args, repo, ["--dsn", "offline", *(["--apply"] if apply else [])]
    )
    assert result == 0
    assert summary["counts"] == {
        "new": 2,
        "identical": 1,
        "mismatch": 1,
        "non_a_share": 1,
        "abnormal": 2,
        "out_of_scope": 1,
    }
    assert repo.reads > 0
    assert all(repo.rows[k] == v for k, v in original.items())
    assert len(repo.rows) == (4 if apply else 2)
    assert repo.writes == (2 if apply else 0)
    assert repo.transaction_modes == [apply, apply]
    assert all(
        v.source == "tdx_local" for k, v in repo.rows.items() if k not in original
    )
    assert sum(b["inserted"] for b in summary["batches"]) == (2 if apply else 0)
    details = [
        json.loads(line)
        for line in (repo.out / "reconcile.jsonl").read_text().splitlines()
    ]
    mismatch = [item for item in details if item["kind"] == "mismatch"]
    assert len(mismatch) == 4
    assert all(item["existing_source"] == "mairui" for item in mismatch)
    assert {
        "code",
        "trade_date",
        "field",
        "existing_value",
        "tdx_value",
        "adj_type",
    } <= mismatch[0].keys()
    assert all(
        b["before"]["mairui"] == b["after"]["mairui"] == 1 for b in summary["batches"]
    )
    keys = [
        r for p in repo.out.glob("*_new_keys.csv") for r in csv.DictReader(p.open())
    ]
    assert len(keys) == 2 and all(r["adj_type"] == "none" for r in keys)


def test_lock_exists_skips_before_input_or_db_access(tmp_path, capsys):
    args = inputs(tmp_path)
    lock = tmp_path / "lock"
    lock.mkdir()

    def forbidden(_):
        pytest.fail("must not connect")

    assert (
        loader.main([*args, "--lock-dir", str(lock), "--apply"], factory=forbidden) == 0
    )
    assert "LOCKED" in capsys.readouterr().out
    assert lock.is_dir() and not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    "failure", ["sha", "missing", "partial_parts", "uncovered", "unsafe"]
)
@pytest.mark.parametrize("apply", [False, True])
def test_integrity_preflight_blocks_all_apply(tmp_path, failure, apply):
    args = inputs(tmp_path)
    root = tmp_path / "history"
    path = root / "day_2001.csv"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if failure == "sha":
        (root / "SUMS").write_text(f"{'0' * 64}  day_2001.csv\n")
    elif failure == "missing":
        (root / "SUMS").write_text(f"{digest}  day_2002.csv\n")
    elif failure == "partial_parts":
        (root / "PARTS").write_text(f"{digest}  p00\n")
        (root / "p00").write_bytes(path.read_bytes())
    elif failure == "unsafe":
        (root / "SUMS").write_text(f"{digest}  ../escape.csv\n")
    else:
        (root / "other.txt").write_text("fiction")
        (root / "SUMS").write_text(
            f"{hashlib.sha256(b'fiction').hexdigest()}  other.txt\n"
        )
    repo = MemoryRepository()
    result, summary = invoke(
        tmp_path, args, repo, ["--dsn", "offline", *(["--apply"] if apply else [])]
    )
    assert result == (2 if apply else 1)
    assert summary["incomplete"]
    assert not summary["integrity"]["history"]["complete"]
    assert repo.writes == 0
    assert (summary["batches"] == []) if apply else len(summary["batches"]) == 2


@pytest.mark.parametrize("mode", ["insert_failure", "mairui_change"])
def test_failed_transaction_rolls_back_and_others_continue(tmp_path, mode):
    args = inputs(tmp_path)
    repo = MemoryRepository()
    original_insert = repo.insert

    def insert(rows):
        repo.fail = mode == "insert_failure" and rows[0][0] == "000001.SZ"
        repo.change_mairui = mode == "mairui_change" and rows[0][0] == "000001.SZ"
        return original_insert(rows)

    repo.insert = insert
    result, summary = invoke(tmp_path, args, repo, ["--dsn", "offline", "--apply"])
    assert result == 1
    assert [b["status"] for b in summary["batches"]] == ["failed", "committed"]
    assert len(repo.rows) == 1
    assert next(iter(repo.rows))[0] == "920001.BJ"
    assert len(list(repo.out.glob("*_new_keys.csv"))) == 2
    assert "synthetic failure" not in (repo.out / "summary.json").read_text()


@pytest.mark.parametrize(
    "change",
    [
        {"volume": "1.1"},
        {"close": "NaN"},
        {"open": "0"},
        {"amount": "-1"},
        {"amount": "10000000000000000"},
        {"trade_date": "20010102"},
        {"adj_type": "hfq"},
        {"open": "10.00001"},
        {"code": "bad"},
        {"high": "9"},
    ],
)
def test_invalid_rows(tmp_path, change):
    args = inputs(tmp_path, history=[row(**change)])
    result, summary = invoke(tmp_path, args, MemoryRepository(), ["--dsn", "offline"])
    assert result == 0 and summary["counts"]["abnormal"] == 1


def test_bad_header_file_failure_does_not_stop_bj(tmp_path):
    args = inputs(tmp_path)
    (tmp_path / "history/day_2001.csv").write_text(
        "code,trade_date\n000001.SZ,2001-01-02\n"
    )
    result, summary = invoke(
        tmp_path, args, MemoryRepository(), ["--dsn", "offline", "--apply"]
    )
    assert result == 1 and summary["batches"][0]["status"] == "failed"
    assert summary["batches"][1]["inserted"] == 1


def test_duplicate_keys_are_abnormal(tmp_path):
    args = inputs(tmp_path, history=[row(), row()])
    result, summary = invoke(tmp_path, args, MemoryRepository(), ["--dsn", "offline"])
    assert result == 0
    assert summary["counts"]["new"] == 2 and summary["counts"]["abnormal"] == 1


def test_bj_zip_full_window_and_caller_filter(tmp_path):
    args = inputs(tmp_path)
    archive = tmp_path / "bj.zip"
    with ZipFile(archive, "w") as zipfile:
        for number in (1, 2, 3):
            zipfile.writestr(
                f"bj/lday/bj92000{number}.day",
                b"".join(
                    DAY_LAYOUT.pack(day, 1000, 1000, 1000, 1000, 1000.0, 100, 0)
                    for day in (20010102, 20310102)
                ),
            )
    args[args.index("--bj-data") + 1] = str(archive)
    result, summary = invoke(tmp_path, args, MemoryRepository(), ["--dsn", "offline"])
    assert result == 0 and summary["bj_codes_requested"] == 2
    assert summary["counts"]["new"] == 5
    assert summary["counts"]["zip_skipped"] == 1
    assert len(summary["batches"]) == 3


def test_valid_sums_and_changed_after_preflight(tmp_path):
    args = inputs(tmp_path)
    root = tmp_path / "history"
    path = root / "day_2001.csv"
    (root / "SUMS").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  day_2001.csv\n"
    )
    repo = MemoryRepository()

    repo.out = tmp_path / "out"

    def factory(_):
        path.write_text("changed")
        return repo

    assert loader.main([*args, "--dsn", "offline", "--apply"], factory=factory) == 1
    summary = json.loads((tmp_path / "out/summary.json").read_text())
    assert summary["batches"][0]["error"] == "input_changed_after_preflight"


def test_transport_bundles_are_verified_and_unpacked(tmp_path):
    import tarfile

    root = tmp_path / "transport"
    root.mkdir()
    csv_data = io.StringIO()
    writer = csv.DictWriter(csv_data, fieldnames=DAY_COLUMNS)
    writer.writeheader()
    writer.writerow(row())
    content = csv_data.getvalue().encode()
    legacy = b"-- synthetic legacy payload: hash only, never execute\n"
    sums = (
        f"{hashlib.sha256(content).hexdigest()}  day_2001.csv\n"
        f"{hashlib.sha256(legacy).hexdigest()}  tb143_load_day.sql\n"
    ).encode()
    bundles = {}
    for i in range(1, 6):
        path = root / f"b{i}.tgz"
        with tarfile.open(path, "w:gz") as archive:
            for name, data in (
                {"day_2001.csv": content, "SUMS": sums, "tb143_load_day.sql": legacy}
                if i == 1
                else {"SUMS": sums}
                if i == 2
                else {}
            ).items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
        bundles[path.name] = path.read_bytes()
    (root / "BUNDLES").write_text(
        "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n"
            for name, data in bundles.items()
        )
    )
    combined = b"".join(bundles.values())
    sizes = [len(data) for data in bundles.values()]
    # 虚构 57 个传输片，保留末片余数。
    stride = len(combined) // 57
    lines = []
    for i in range(57):
        data = (
            combined[i * stride : (i + 1) * stride]
            if i < 56
            else combined[i * stride :]
        )
        (root / f"p{i:02d}").write_bytes(data)
        lines.append(f"{hashlib.sha256(data).hexdigest()}  p{i:02d}\n")
    (root / "PARTS").write_text("".join(lines))
    for name in bundles:
        (root / name).unlink()
    result = prepare(root, tmp_path / "prepared", ",".join(map(str, sizes)))
    assert result.errors == [] and len(result.files) == 1
    assert result.files[0].read_bytes() == content
    assert (result.files[0].parent / "tb143_load_day.sql").read_bytes() == legacy


def test_sql_is_append_only_and_fixed_source():
    sql = loader.INSERT_SQL.upper()
    assert "ON CONFLICT (CODE, TRADE_DATE, ADJ_TYPE) DO NOTHING" in sql
    assert "UPDATE" not in sql and "DELETE" not in sql and "'TDX_LOCAL'" in sql
    assert "D.ADJ_TYPE='NONE'" in loader.KEY_SQL.upper()


@pytest.fixture(scope="module")
def isolated_pg():
    """只启动本机一次性 PG；绝不采用环境中的任何数据库 URL。"""
    initdb, pg_ctl = shutil.which("initdb"), shutil.which("pg_ctl")
    if not initdb or not pg_ctl:
        pytest.skip("PG 未实跑：没有本机 initdb/pg_ctl（不连接外部测试库）")
    with tempfile.TemporaryDirectory(prefix="reconcile_pg_", dir="/tmp") as temporary:
        root = Path(temporary)
        data = root / "db"
        subprocess.run(
            [initdb, "-D", str(data), "--auth=trust", "--no-locale", "-U", "fixture"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                pg_ctl,
                "-D",
                str(data),
                "-l",
                str(root / "pg.log"),
                "-o",
                f"-F -k {root} -h '' -p 55483",
                "-w",
                "start",
            ],
            check=True,
            capture_output=True,
        )
        try:
            yield f"host={root} port=55483 user=fixture dbname=postgres"
        finally:
            subprocess.run(
                [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
                check=True,
                capture_output=True,
            )


@pytest.mark.parametrize("failure", [None, "insert", "mairui", "dry"])
def test_real_pg_transaction_and_preservation(tmp_path, isolated_pg, failure):
    args = inputs(tmp_path, history=[row(day="2001-01-02"), row(day="2001-01-03")])
    with psycopg.connect(isolated_pg, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS market CASCADE; CREATE SCHEMA market")
        conn.execute("""
            CREATE TABLE market.securities(code text, type text, listing_status text);
            INSERT INTO market.securities VALUES ('000001.SZ','stock','listed'),
                                                ('920001.BJ','stock','listed');
            CREATE TABLE market.daily_bars(
                code text, trade_date date, adj_type text,
                open numeric(20,4), high numeric(20,4), low numeric(20,4), close numeric(20,4),
                volume numeric(20,4), amount numeric(20,4), source text,
                pre_close numeric, is_suspended boolean, source_licence_id uuid,
                fetched_at timestamptz, PRIMARY KEY(code,trade_date,adj_type));
            INSERT INTO market.daily_bars(code,trade_date,adj_type,open,high,low,close,volume,amount,source)
                VALUES ('000001.SZ','2001-01-03','none',11,11,11,11,100,1100,'mairui');
        """)
        if failure == "insert":
            conn.execute("ALTER TABLE market.daily_bars ADD CHECK(source='mairui')")
        elif failure == "mairui":
            conn.execute("""
                CREATE FUNCTION market.side_effect() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                  IF NEW.source = 'tdx_local' THEN
                    INSERT INTO market.daily_bars(code,trade_date,adj_type,source)
                    VALUES ('000002.SZ',NEW.trade_date,'none','mairui');
                  END IF;
                  RETURN NEW;
                END $$;
                CREATE TRIGGER side_effect AFTER INSERT ON market.daily_bars
                FOR EACH ROW EXECUTE FUNCTION market.side_effect();
            """)
        failed = failure in ("insert", "mairui")
        extra = [] if failure == "dry" else ["--apply"]
        assert loader.main([*args, "--dsn", isolated_pg, *extra]) == (
            1 if failed else 0
        )
        assert conn.execute("SELECT count(*) FROM market.daily_bars").fetchone() == (
            (1 if failure else 3),
        )
        assert conn.execute(
            "SELECT close FROM market.daily_bars WHERE source='mairui'"
        ).fetchall() == [(Decimal(11),)]
        summary = json.loads((tmp_path / "out/summary.json").read_text())
        assert all(
            batch["status"]
            == ("failed" if failed else "dry_run" if failure == "dry" else "committed")
            for batch in summary["batches"]
        )
        conn.execute("DROP SCHEMA market CASCADE")


@pytest.mark.parametrize("invalid_codes", [False, True])
def test_owned_lock_is_released_on_success_and_failure(tmp_path, invalid_codes):
    args = inputs(tmp_path)
    if invalid_codes:
        (tmp_path / "codes.txt").write_text("invalid")
    lock = tmp_path / "lock"
    repo = MemoryRepository()
    result, _ = invoke(
        tmp_path, args, repo, ["--dsn", "offline", "--lock-dir", str(lock)]
    )
    assert result == (2 if invalid_codes else 0)
    assert not lock.exists()
    assert repo.writes == 0


def test_existing_tdx_mismatch_is_preserved_on_apply(tmp_path):
    args = inputs(tmp_path)
    repo = MemoryRepository()
    existing_key = ("000001.SZ", date(2001, 1, 2), "none")
    repo.rows[existing_key] = old("tdx_local", price="12")
    original = repo.rows[existing_key]
    result, summary = invoke(tmp_path, args, repo, ["--dsn", "offline", "--apply"])
    assert result == 0 and repo.rows[existing_key] == original
    assert summary["counts"]["mismatch"] == 1
    assert sum(batch["inserted"] for batch in summary["batches"]) == 1


def test_csv_parser_failure_rolls_back_file_and_continues(tmp_path):
    args = inputs(tmp_path)
    path = tmp_path / "history/day_2001.csv"
    with path.open("a") as stream:
        stream.write('"unterminated')
    repo = MemoryRepository()
    result, summary = invoke(tmp_path, args, repo, ["--dsn", "offline", "--apply"])
    assert result == 1 and summary["batches"][0]["error"] == "Error"
    assert [key[0] for key in repo.rows] == ["920001.BJ"]
    assert summary["batches"][1]["status"] == "committed"


def test_input_symlink_escape_is_not_opened(tmp_path, monkeypatch):
    from app.cli import tb143_inputs

    root = tmp_path / "history"
    root.mkdir()
    outside = tmp_path / "fiction.csv"
    outside.write_text("synthetic,not_to_be_opened")
    (root / "day_escape.csv").symlink_to(outside)
    (root / "SUMS").symlink_to(outside)

    def forbidden(_):
        pytest.fail("escaped file must not be hashed")

    monkeypatch.setattr(tb143_inputs, "file_sha256", forbidden)
    result = tb143_inputs.prepare(root, tmp_path / "prepared")
    assert result.files == []
    assert {"SUMS:unsafe_manifest_path", "csv:unsafe_path"} <= set(result.errors)
