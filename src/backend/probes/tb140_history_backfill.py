#!/usr/bin/env python3
"""T-B140c 单进程单连接日线历史回填器（stdlib http.client）。

本模块默认不出网：只有在命令行显式给出 --licence-file 且账本未熔断时才会请求。
离线自检请用 tb140_history_selfcheck.py，或注入 connection_factory。
整批自续接与写库请用 tb140_history_supervisor.py。

约束（与派单一致）：
- 只读调用方指定的 0600 临时证书文件，读入内存后立即删除；不读环境变量、不读 .env。
- 不打印证书，异常与 URL 日志一律脱敏。异常只记录类名与时间，不记消息文本。
- 先记账后请求；原子更新计数；持久化断点。
- 传输失败（断开/超时/连不上）：关连接、等 60 秒、重建连接续接同一只；进程累计最多续接 3 次，第 4 次 halted+STOP。每次重试也先记账。
- HTTP 429 / 业务码 101、103、429 / STOP / HTTP 503 / 其他非 200 或业务限流：立即 halted+追加 STOP，不重试。
- 非 200 时把响应体前 300 字节脱敏后记入 runs.jsonl。
- 不清除旧 STOP（只追加原因，从不 unlink / 覆盖清空）。
- 每批最多 2000；请求间隔默认 1 秒，下限 0.2 秒（t1153s3904；T003-mairui-capability）。
- 麦蕊连接直接使用 http.client，不读取代理环境变量，不设置隧道。
- 数据只写 --run-dir，不入仓库。
- 容器无 requests/httpx；本文件只使用标准库 + 同目录 tb140_history_load。
- 不提供清 STOP、复位 halted、从 0 建账本的开关。
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import ssl
import stat
import sys
import time
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

if __package__:
    from .tb140_history_load import (
        CodeReject,
        _bj_write_unconfirmed,
        RowReject,
        market_of,
        parse_window,
        plan_history_expansion,
        requestable_history_codes,
        normalize_history,
        qualified_code,
        render_insert_sql,
        resolve_active_licence,
        write_normalized,
    )
else:
    from tb140_history_load import (
        CodeReject,
        _bj_write_unconfirmed,
        RowReject,
        market_of,
        parse_window,
        plan_history_expansion,
        requestable_history_codes,
        normalize_history,
        qualified_code,
        render_insert_sql,
        resolve_active_licence,
        write_normalized,
    )

HOST = "api.mairuiapi.com"
BATCH_CAP = 2000
# 用户卡片 t1153s3904：每秒 5 次、单进程直连、遇限流即停；
# T003-mairui-capability：钻石版 6000 次/分钟、每日不限。
RATE_FLOOR_SECONDS = 0.2
MIN_INTERVAL = RATE_FLOOR_SECONDS
DEFAULT_INTERVAL = 1.0
MAX_BODY = 10 * 1024 * 1024
HTTP_BODY_PREVIEW_BYTES = 300
TRANSPORT_RESUME_LIMIT = 3
TRANSPORT_RESUME_WAIT = 60.0
SCHEMA = "T-B140/v1"
MST = ZoneInfo("America/Denver")
LIMIT_KEYS = ("限流", "超出", "超过", "频繁", "上限", "次数")
LIMIT_CODE = re.compile(r"(?<!\d)(?:101|103|429)\s*[:：]")


class Halt(Exception):
    """固定、不含密钥的停机原因。"""


class TransportFailure(Exception):
    """传输层失败，只携带异常类名，不含消息文本。"""

    def __init__(self, exc_class: str) -> None:
        self.exc_class = exc_class
        super().__init__(exc_class)


def now_mst() -> str:
    return datetime.now(MST).isoformat()


def redact(text: str, secret: str) -> str:
    if not secret:
        return text
    out = text.replace(secret, "***")
    encoded = quote(secret, safe="")
    if encoded and encoded != secret:
        out = out.replace(encoded, "***")
    return out


def _reason(exc: BaseException) -> str:
    if isinstance(exc, Halt):
        return str(exc) or "halted"
    if isinstance(exc, TransportFailure):
        return f"transport_failure:{exc.exc_class}"
    return "transport_or_internal_failure_no_retry"


def _is_transport(exc: BaseException) -> bool:
    if isinstance(exc, (Halt, TransportFailure)):
        return False
    if isinstance(
        exc,
        (
            ConnectionError,
            TimeoutError,
            ssl.SSLError,
            http.client.HTTPException,
            OSError,
        ),
    ):
        return True
    return False


def read_licence_file(path: Path) -> str:
    try:
        info = path.lstat()
    except OSError as exc:
        raise Halt("licence_file_unreadable") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise Halt("licence_file_permissions_invalid")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise Halt("licence_file_permissions_invalid")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        raw = os.read(fd, 4096)
    finally:
        os.close(fd)
    secret = raw.decode("utf-8", errors="strict").strip()
    if not secret or "\n" in secret or "\r" in secret:
        raise Halt("licence_file_empty_or_multiline")
    return secret


def delete_licence_file(path: Path | None) -> bool:
    if path is None:
        return True
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return not path.exists()
    return not path.exists()


def load_codes(path: Path) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        if item in seen:
            continue
        market_of(item)  # 未知前缀直接拒绝，避免宽泛回落
        codes.append(item)
        seen.add(item)
    return codes


def default_counter() -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "total": 0,
        "halted": False,
        "halt_reason": None,
        "by_kind": {},
        "done_history": [],
    }


def atomic_save(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_counter(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise Halt("counter_missing_fail_closed")
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise Halt("counter_permissions_invalid")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise Halt("counter_permissions_invalid")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Halt("counter_state_unknown") from exc
    if not isinstance(state, dict) or state.get("schema") != SCHEMA:
        raise Halt("counter_state_unknown")
    if type(state.get("total")) is not int or type(state.get("halted")) is not bool:
        raise Halt("counter_state_unknown")
    if state["total"] < 0:
        raise Halt("counter_state_unknown")
    if not isinstance(state.get("by_kind"), dict):
        state["by_kind"] = {}
    if not isinstance(state.get("done_history"), list):
        state["done_history"] = []
    return state


def append_stop(path: Path, reason: str) -> None:
    """只追加，不删除、不把旧内容清空。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = f"{now_mst()} {reason}\n"
    fd = os.open(
        str(path),
        os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
        0o600,
    )
    try:
        os.write(fd, line.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def business_limited(status: int, body: Any) -> bool:
    if status in {101, 103, 429}:
        return True
    if isinstance(body, (str, int)) and str(body) in {"101", "103", "429"}:
        return True
    if isinstance(body, str) and (LIMIT_CODE.search(body) or any(k in body for k in LIMIT_KEYS)):
        return True
    if isinstance(body, dict):
        text = json.dumps(body, ensure_ascii=False)
        if LIMIT_CODE.search(text) or any(k in text for k in LIMIT_KEYS):
            return True
        for key in ("code", "error_code", "status", "errcode"):
            if key in body and str(body[key]) in {"101", "102", "103", "429"}:
                return True
    return False


def _history_route(code: str, token: str, st: str | date | None, et: str | date | None) -> str:
    code = code.strip()
    market = market_of(code)
    start, end = parse_window(st, et)
    query = urlencode({key: day.isoformat().replace("-", "") for key, day in (("st", start), ("et", end)) if day is not None})
    route = "bj" if market == "BJ" else "hsstock"
    path = f"/{route}/history/{qualified_code(code)}/d/n/{token}"
    return path + ("?" + query if query else "")


def history_path(code: str, secret: str, st: str | date | None = None, et: str | date | None = None) -> str:
    return _history_route(code, quote(secret, safe=""), st, et)


def history_path_log(code: str, st: str | date | None = None, et: str | date | None = None) -> str:
    return _history_route(code, "***", st, et)


def open_connection(timeout: float = 40.0) -> http.client.HTTPSConnection:
    """直连固定主机；http.client 不读取代理环境变量，也不设置隧道。"""
    context = ssl.create_default_context()
    return http.client.HTTPSConnection(HOST, timeout=timeout, context=context)


def request_once(conn: Any, path: str) -> tuple[int, Any, bytes]:
    status: int | None = None
    try:
        conn.request(
            "GET",
            path,
            headers={
                "Host": HOST,
                "Accept": "application/json",
                "Connection": "keep-alive",
            },
        )
        resp = conn.getresponse()
        status = int(resp.status)
        raw = resp.read(HTTP_BODY_PREVIEW_BYTES if status != 200 else MAX_BODY + 1)
    except Halt:
        raise
    except BaseException as exc:
        if status is not None and status != 200:
            # 已收到非 200，响应体读取失败也必须熔断，不能误判为可续接传输错误。
            return status, None, b""
        if _is_transport(exc):
            raise TransportFailure(type(exc).__name__) from None
        raise Halt("transport_or_internal_failure_no_retry") from None
    if status != 200:
        return status, raw.decode("utf-8", errors="replace"), raw
    if len(raw) > MAX_BODY:
        raise Halt("response_too_large")
    preview = raw[:HTTP_BODY_PREVIEW_BYTES]
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Halt("response_not_utf8") from None
    body: Any
    if not text:
        body = None
    else:
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = text
    return status, body, preview


class Backfill:
    def __init__(
        self,
        *,
        counter_path: Path,
        stop_path: Path,
        run_dir: Path,
        interval: float = DEFAULT_INTERVAL,
        connection_factory: Callable[[], Any] | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if interval < MIN_INTERVAL:
            raise Halt("interval_below_minimum")
        self.counter_path = counter_path
        self.stop_path = stop_path
        self.run_dir = run_dir
        self.interval = interval
        self.connection_factory = connection_factory or open_connection
        self.sleeper = sleeper
        self.clock = clock
        self.last_request_at: float | None = None
        self.conn: Any = None
        self.calls_this_run = 0
        self.transport_resumes = 0
        self.transport_events: list[dict[str, str]] = []
        self.last_http_preview: bytes | None = None
        self.last_http_status: int | None = None

    def _refuse_if_stopped(self, state: dict[str, Any]) -> None:
        if self.stop_path.exists():
            self._persist_halt(state, "STOP")
            raise Halt("STOP")
        if state.get("halted"):
            raise Halt("halted")

    def _persist_halt(self, state: dict[str, Any], reason: str) -> None:
        state["halted"] = True
        state["halt_reason"] = reason
        atomic_save(self.counter_path, state)
        append_stop(self.stop_path, reason)

    def _wait_interval(self) -> None:
        now = self.clock()
        if self.last_request_at is None:
            delay = self.interval
        else:
            delay = self.interval - (now - self.last_request_at)
        if delay > 0:
            self.sleeper(delay)

    def _reserve(self, state: dict[str, Any], kind: str) -> dict[str, Any]:
        self._refuse_if_stopped(state)
        state["total"] = int(state["total"]) + 1
        kinds = state.setdefault("by_kind", {})
        kinds[kind] = int(kinds.get(kind, 0)) + 1
        atomic_save(self.counter_path, state)
        return state

    def _note_transport(self, exc_class: str) -> None:
        self.transport_events.append({"at": now_mst(), "exc_class": exc_class})

    def _open_conn(self) -> Any:
        try:
            return self.connection_factory()
        except Halt:
            raise
        except TransportFailure:
            raise
        except BaseException as exc:
            if _is_transport(exc):
                raise TransportFailure(type(exc).__name__) from None
            raise Halt("transport_or_internal_failure_no_retry") from None

    def call_history(self, state: dict[str, Any], secret: str, code: str, st: str | date | None = None, et: str | date | None = None) -> tuple[int, Any]:
        path = history_path(code, secret, st, et)  # 参数错误发生在记账、建连之前
        accepted, _ = requestable_history_codes([code])
        if not accepted:
            raise Halt("旧码不请求")
        self._refuse_if_stopped(state)
        while True:
            self._wait_interval()
            self._refuse_if_stopped(state)
            self._reserve(state, "history")
            self.calls_this_run += 1  # 已记账即计入本轮 calls，含随后的 429/断开/重试
            outcome: str | None = None
            payload: tuple[int, Any] | None = None
            try:
                if self.conn is None:
                    self.conn = self._open_conn()
                status, body, preview = request_once(self.conn, path)
                if status != 200 or business_limited(status, body):
                    if status != 200:
                        self.last_http_preview = preview
                        self.last_http_status = status
                    reason = f"HTTP_{status}" if status != 200 else "business_rate_limit"
                    if business_limited(status, body):
                        reason = f"HTTP_{status}:rate_or_quota"
                    self._persist_halt(state, reason)
                    raise Halt(reason)
                payload = (status, body)
                outcome = "ok"
            except TransportFailure as exc:
                self._note_transport(exc.exc_class)
                self.close()
                if self.transport_resumes >= TRANSPORT_RESUME_LIMIT:
                    self._persist_halt(state, f"transport_failure:{exc.exc_class}")
                    raise Halt(f"transport_failure:{exc.exc_class}") from None
                self.transport_resumes += 1
                self.sleeper(TRANSPORT_RESUME_WAIT)
                outcome = "retry"
            except Halt:
                raise
            finally:
                self.last_request_at = self.clock()
            if outcome == "ok" and payload is not None:
                return payload
            # outcome == "retry"：续接同一只，再记账后再请求

    def close(self) -> None:
        conn = self.conn
        self.conn = None
        if conn is not None:
            try:
                conn.close()
            except BaseException:
                pass


def _safe_persist(
    persist_rows: Callable[[list[dict[str, Any]]], dict[str, Any]],
    rows: list[dict[str, Any]],
    engine: Backfill,
    state: dict[str, Any],
    summary: dict[str, Any],
) -> None:
    if not rows:
        return
    try:
        stats = persist_rows(rows)
    except Halt:
        raise
    except BaseException:
        engine._persist_halt(state, "db_write_failed")
        raise Halt("db_write_failed") from None
    summary["db_count_before"] = stats.get("count_before")
    summary["db_count_after"] = stats.get("count_after")
    summary["db_inserted"] = stats.get("inserted")
    summary["db_replaced"] = stats.get("replaced", 0)
    if stats.get("blocked_bj_unconfirmed"):
        summary["db_blocked_bj_unconfirmed"] = stats["blocked_bj_unconfirmed"]


def run_batch(
    *,
    codes_file: Path,
    licence_file: Path | None,
    counter_path: Path,
    stop_path: Path,
    run_dir: Path,
    max_calls: int = BATCH_CAP,
    interval: float = DEFAULT_INTERVAL,
    st: str | date | None = None,
    et: str | date | None = None,
    licence_ids: list[str] | None = None,
    connection_factory: Callable[[], Any] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    engine: Backfill | None = None,
    secret: str | None = None,
    close_engine: bool = True,
    persist_rows: Callable[[list[dict[str, Any]]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        start, end = parse_window(st, et)
    except RowReject as exc:
        raise Halt(str(exc)) from None
    if max_calls < 1 or max_calls > BATCH_CAP:
        raise Halt("batch_cap_invalid")
    run_dir.mkdir(parents=True, exist_ok=True)
    bars_dir = run_dir / "history"
    sql_dir = run_dir / "sql"
    bars_dir.mkdir(exist_ok=True)
    sql_dir.mkdir(exist_ok=True)
    local_secret = secret or ""
    summary: dict[str, Any] = {
        "mode": "history",
        "started_mst": now_mst(),
        "calls": 0,
        "halt": None,
        "done": 0,
        "written_bars": 0,
        "rejected_rows": 0,
        "sql_files": 0,
    }
    state: dict[str, Any] = {}
    written_rows: list[dict[str, Any]] = []
    calls_before = 0
    persist_attempted = False
    completed_codes: list[str] = []
    blocked_codes: set[str] = set()

    def record_completed() -> None:
        for code in completed_codes:
            if _bj_write_unconfirmed({"code": qualified_code(code)}) or (
                market_of(code) == "BJ" and summary.get("db_blocked_bj_unconfirmed")
            ):
                blocked_codes.add(code)
            if code in blocked_codes:
                continue
            state.setdefault("done_history", []).append(code)
            state.setdefault("history_windows", {})[code] = {
                "st": start.isoformat() if start else None,
                "et": end.isoformat() if end else None,
            }
            summary["done"] += 1
        summary["blocked_bj_unconfirmed"] = sorted(blocked_codes)
        summary["remaining"] = len([c for c in codes if c not in state.get("done_history", [])])
        if summary["done"]:
            atomic_save(counter_path, state)

    try:
        state = load_counter(counter_path)
        if engine is None:
            engine = Backfill(
                counter_path=counter_path,
                stop_path=stop_path,
                run_dir=run_dir,
                interval=interval,
                connection_factory=connection_factory,
                sleeper=sleeper,
                clock=clock,
            )
        calls_before = engine.calls_this_run
        engine._refuse_if_stopped(state)
        if not local_secret:
            if licence_file is None:
                raise Halt("licence_file_unreadable")
            local_secret = read_licence_file(licence_file)
            if not delete_licence_file(licence_file):
                raise Halt("licence_file_delete_failed")
        elif licence_file is not None and licence_file.exists():
            # 调用方已把证书读入内存时，仍清掉残留临时文件
            delete_licence_file(licence_file)
        codes, skipped = requestable_history_codes(load_codes(codes_file))
        summary["skipped_codes"] = skipped
        summary["expansion_plan"] = plan_history_expansion(state, ledger_path=counter_path, st=start, et=end)
        done = {str(x) for x in state.get("done_history") or []}
        todo = [c for c in codes if c not in done][:max_calls]
        summary["todo"] = len(todo)
        summary["remaining_before"] = len([c for c in codes if c not in done])
        lid, bind_note = resolve_active_licence(licence_ids or [])
        summary["licence_bind"] = bind_note
        sql_names: list[str] = []
        for code in todo:
            _status, body = engine.call_history(state, local_secret, code, start, end)
            try:
                rows, rejects = normalize_history(code, body, st=start, et=end)
            except (RowReject, CodeReject) as exc:
                engine._persist_halt(state, f"payload_invalid:{exc}")
                raise Halt(f"payload_invalid:{exc}") from None
            qcode = qualified_code(code)
            write_normalized(bars_dir / f"{qcode}.json", code, rows, rejects, st=start, et=end)
            sql_path = sql_dir / f"{qcode}.sql"
            sql_path.write_text(render_insert_sql(rows, lid, bind_note=bind_note), encoding="utf-8")
            sql_names.append(str(sql_path.name))
            completed_codes.append(code)
            if _bj_write_unconfirmed({"code": qcode}):
                blocked_codes.add(code)
            summary["written_bars"] += len(rows)
            summary["rejected_rows"] += len(rejects)
            summary["sql_files"] += 1
            written_rows.extend(rows)
        if bind_note != "bound":
            (run_dir / "pending_bind.json").write_text(
                json.dumps({"note": bind_note, "source_licence_id": lid, "at": now_mst()}, ensure_ascii=False),
                encoding="utf-8",
            )
        summary["sql"] = sql_names
        if persist_rows is not None:
            persist_attempted = True
            _safe_persist(persist_rows, written_rows, engine, state, summary)
        record_completed()
        return summary
    except Halt as exc:
        summary["halt"] = str(exc)
        if persist_rows is not None and written_rows and engine is not None and not persist_attempted:
            try:
                _safe_persist(persist_rows, written_rows, engine, state, summary)
                record_completed()
            except Halt as db_exc:
                summary["halt"] = str(db_exc)
        raise
    finally:
        if engine is not None:
            summary["calls"] = engine.calls_this_run - calls_before
            events = [
                {"at": ev.get("at", ""), "exc_class": ev.get("exc_class", "")}
                for ev in engine.transport_events
            ]
            summary["transport_events"] = events
            summary["transport_resumes"] = engine.transport_resumes
            if engine.last_http_preview is not None:
                preview_text = engine.last_http_preview.decode("utf-8", errors="replace")
                summary["http_body_preview"] = redact(preview_text, local_secret)
                summary["http_status"] = engine.last_http_status
            if close_engine:
                engine.close()
        deleted = delete_licence_file(licence_file)
        summary["licence_deleted"] = deleted
        summary["total"] = state.get("total")
        summary["halted"] = state.get("halted")
        summary["finished_mst"] = now_mst()
        text = redact(json.dumps(summary, ensure_ascii=False), local_secret)
        local_secret = ""
        (run_dir / "runs.jsonl").open("a", encoding="utf-8").write(text + "\n")
        print(text)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="T-B140c history backfill (stdlib http.client)")
    p.add_argument("--codes-file", type=Path, required=True)
    p.add_argument("--licence-file", type=Path, required=True, help="调用方准备的 0600 临时证书；读入后立即删除")
    p.add_argument("--counter", type=Path, required=True, help="已有账本路径；缺失则 fail-closed，不从 0 新建")
    p.add_argument("--stop-file", type=Path, required=True)
    p.add_argument("--run-dir", type=Path, required=True, help="原始与 SQL 只写这里，勿放仓库内")
    p.add_argument("--max", type=int, default=BATCH_CAP)
    p.add_argument("--interval", type=float, default=DEFAULT_INTERVAL, help="请求间隔秒，默认 1，小于 0.2 拒绝")
    p.add_argument("--st", default=None)
    p.add_argument("--et", default=None)
    p.add_argument(
        "--licence-id",
        action="append",
        default=[],
        help="已查到的 active 证书 UUID；可重复。不查库；缺省则 SQL 写 NULL 并记 pending_bind",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_batch(
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
        )
        return 0
    except Halt:
        return 1


if __name__ == "__main__":
    sys.exit(main())
