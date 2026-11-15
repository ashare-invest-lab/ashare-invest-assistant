#!/usr/bin/env python3
"""T-B140 自续接回填：一个进程跑完全部剩余代码并自行写库。

在 aia-local-ingest-1 内启动。证书只在启动时从 --licence-file 读入内存并立即删文件。
单进程、单条 HTTP 长连接；批与批之间只写库再继续，靠账本 done_history 断点续接。
不依赖外部逐批启动，也不提供清 STOP / 复位 halted / 从 0 建账本的开关。

默认请求间隔 2 秒；--interval 小于 0.2 拒绝（t1153s3904；T003-mairui-capability）。
麦蕊连接直接使用 http.client，不读代理变量值、不设置隧道；启动汇总只记录代理变量是否存在。
数据库连接串只从 --db-url-env 指定名字的环境变量读取（默认 DATABASE_URL），不打印连接串。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

if __package__:
    from .tb140_history_backfill import (
        BATCH_CAP,
        RATE_FLOOR_SECONDS,
        Halt,
        Backfill,
        delete_licence_file,
        load_codes,
        load_counter,
        now_mst,
        read_licence_file,
        redact,
        run_batch,
    )
else:
    from tb140_history_backfill import (
        BATCH_CAP,
        RATE_FLOOR_SECONDS,
        Halt,
        Backfill,
        delete_licence_file,
        load_codes,
        load_counter,
        now_mst,
        read_licence_file,
        redact,
        run_batch,
    )
if __package__:
    from .tb140_history_load import (
        RowReject,
        parse_window,
        requestable_history_codes,
        plan_history_expansion,
        jsonl_reconcile_sink,
        apply_daily_bars,
        resolve_active_licence,
        to_psycopg_dsn,
    )
else:
    from tb140_history_load import (
        RowReject,
        parse_window,
        requestable_history_codes,
        plan_history_expansion,
        jsonl_reconcile_sink,
        apply_daily_bars,
        resolve_active_licence,
        to_psycopg_dsn,
    )

SUPERVISOR_MIN_INTERVAL = RATE_FLOOR_SECONDS
SUPERVISOR_DEFAULT_INTERVAL = 2.0
PROXY_ENV_NAMES = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
DEFAULT_DB_URL_ENV = "DATABASE_URL"
# 默认环境变量名出处：
# src/backend/app/config.py 中 Settings.database_url，
# SettingsConfigDict(env_prefix="")，类文档「字段名大写即对应环境变量名（大小写不敏感）」；
# ingest 容器同样依赖该变量，见 src/backend/app/workers/ingest.py。
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_named_dsn(env_name: str, environ: Mapping[str, str]) -> str:
    """按名字读取连接串并转成 psycopg 可用形式。失败时不包含连接串或变量值。"""
    if not _ENV_NAME_RE.fullmatch(env_name):
        raise Halt("db_url_env_name_invalid")
    try:
        raw = environ.get(env_name)
    except Exception:
        raise Halt("db_url_missing") from None
    if raw is None or not str(raw).strip():
        raise Halt("db_url_missing")
    try:
        return to_psycopg_dsn(str(raw))
    except Exception:
        raise Halt("db_url_invalid") from None


def default_psycopg_connect(dsn: str) -> Any:
    """延迟导入 psycopg，避免自检在无该库时失败。不打印 dsn。"""
    try:
        import psycopg  # type: ignore
    except ImportError as exc:
        raise Halt("psycopg_missing") from exc
    try:
        return psycopg.connect(dsn)
    except Halt:
        raise
    except BaseException:
        raise Halt("db_connect_failed") from None


def run_supervised(
    *,
    codes_file: Path,
    licence_file: Path,
    counter_path: Path,
    stop_path: Path,
    run_dir: Path,
    max_calls: int = BATCH_CAP,
    interval: float = SUPERVISOR_DEFAULT_INTERVAL,
    st: str | date | None = None,
    et: str | date | None = None,
    licence_ids: list[str] | None = None,
    connection_factory: Callable[[], Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    db_url_env: str = DEFAULT_DB_URL_ENV,
    environ: Mapping[str, str] | None = None,
    db_connect: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """跑完账本中尚未完成的全部代码；每批（含熔断已完成部分）单事务写库。"""
    try:
        st, et = parse_window(st, et)
    except RowReject as exc:
        raise Halt(str(exc)) from None
    run_dir.mkdir(parents=True, exist_ok=True)
    env = environ if environ is not None else os.environ
    secret = ""
    db_conn: Any = None
    engine: Backfill | None = None
    overall: dict[str, Any] = {
        "mode": "history_supervised",
        "started_mst": now_mst(),
        "batches": 0,
        "done": 0,
        "halt": None,
        "licence_deleted": False,
        "proxy_env_present": any(name in env for name in PROXY_ENV_NAMES),
    }
    try:
        if interval < SUPERVISOR_MIN_INTERVAL:
            raise Halt("interval_below_minimum")
        if max_calls < 1 or max_calls > BATCH_CAP:
            raise Halt("batch_cap_invalid")
        state = load_counter(counter_path)
        engine = Backfill(
            counter_path=counter_path,
            stop_path=stop_path,
            run_dir=run_dir,
            interval=interval,
            connection_factory=connection_factory,
            sleeper=sleeper,
            clock=clock,
        )
        engine._refuse_if_stopped(state)
        secret = read_licence_file(licence_file)
        if not delete_licence_file(licence_file):
            raise Halt("licence_file_delete_failed")
        overall["licence_deleted"] = True
        dsn = read_named_dsn(db_url_env, env)
        connector = db_connect or default_psycopg_connect
        try:
            db_conn = connector(dsn)
        except Halt:
            raise
        except BaseException:
            raise Halt("db_connect_failed") from None
        dsn = ""
        lid, bind_note = resolve_active_licence(licence_ids or [])
        overall["licence_bind"] = bind_note

        def persist(rows: list[dict[str, Any]]) -> dict[str, Any]:
            return apply_daily_bars(db_conn, rows, lid, reconcile_sink=jsonl_reconcile_sink(run_dir / "reconcile.jsonl"))

        while True:
            state = load_counter(counter_path)
            engine._refuse_if_stopped(state)
            codes, skipped = requestable_history_codes(load_codes(codes_file))
            overall["skipped_codes"] = skipped
            overall["expansion_plan"] = plan_history_expansion(state, ledger_path=counter_path, st=st, et=et)
            done = {str(x) for x in state.get("done_history") or []}
            remaining = [c for c in codes if c not in done]
            if not remaining:
                break
            try:
                summary = run_batch(
                    codes_file=codes_file,
                    licence_file=licence_file,
                    counter_path=counter_path,
                    stop_path=stop_path,
                    run_dir=run_dir,
                    max_calls=min(max_calls, len(remaining)),
                    interval=interval,
                    st=st,
                    et=et,
                    licence_ids=licence_ids,
                    connection_factory=connection_factory,
                    sleeper=sleeper,
                    clock=clock,
                    engine=engine,
                    secret=secret,
                    close_engine=False,
                    persist_rows=persist,
                )
            except Halt as exc:
                overall["halt"] = str(exc)
                overall["batches"] += 1
                raise
            overall["batches"] += 1
            overall["done"] += int(summary.get("done") or 0)
        return overall
    except Halt as exc:
        overall["halt"] = str(exc)
        raise
    finally:
        if engine is not None:
            overall["transport_resumes"] = engine.transport_resumes
            overall["calls"] = engine.calls_this_run
            engine.close()
        if db_conn is not None:
            try:
                db_conn.close()
            except BaseException:
                pass
        deleted = delete_licence_file(licence_file)
        overall["licence_deleted"] = bool(overall.get("licence_deleted") or deleted)
        overall["finished_mst"] = now_mst()
        # 再读一次账本状态写入汇总；失败则忽略
        try:
            final_state = load_counter(counter_path)
            overall["total"] = final_state.get("total")
            overall["halted"] = final_state.get("halted")
            overall["remaining"] = None
        except Halt:
            pass
        text = redact(json.dumps(overall, ensure_ascii=False), secret)
        secret = ""
        (run_dir / "runs.jsonl").open("a", encoding="utf-8").write(text + "\n")
        print(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="T-B140 history backfill supervisor (self-resume, self-write)")
    p.add_argument("--codes-file", type=Path, required=True)
    p.add_argument("--licence-file", type=Path, required=True, help="调用方准备的 0600 临时证书；启动时读入内存后立即删除")
    p.add_argument("--counter", type=Path, required=True, help="已有账本路径；缺失则 fail-closed，不从 0 新建")
    p.add_argument("--stop-file", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True, help="原始与 SQL 只写这里，勿放仓库内")
    p.add_argument("--max", type=int, default=BATCH_CAP, help="每批上限，默认 2000，不能更大")
    p.add_argument("--interval", type=float, default=SUPERVISOR_DEFAULT_INTERVAL, help="请求间隔秒，默认 2，小于 0.2 拒绝")
    p.add_argument("--st", default=None)
    p.add_argument("--et", default=None)
    p.add_argument(
        "--licence-id",
        action="append",
        default=[],
        help="已查到的 active 证书 UUID；可重复。不查库；缺省则 SQL 写 NULL 并记 pending_bind",
    )
    p.add_argument(
        "--db-url-env",
        default=DEFAULT_DB_URL_ENV,
        help="存放数据库连接串的环境变量名（只给名字，不在此填写连接串）。默认 DATABASE_URL",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_supervised(
            codes_file=args.codes_file,
            licence_file=args.licence_file,
            counter_path=args.counter,
            stop_path=args.stop_file,
            run_dir=args.run_dir,
            max_calls=args.max,
            interval=args.interval,
            st=args.st,
            et=args.et,
            licence_ids=list(args.licence_id),
            db_url_env=args.db_url_env,
        )
        return 0
    except Halt:
        return 1


if __name__ == "__main__":
    sys.exit(main())
