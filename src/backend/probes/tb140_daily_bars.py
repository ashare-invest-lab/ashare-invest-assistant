#!/usr/bin/env python3
# ruff: noqa
"""T-B140 麦蕊日线实调器（box 侧，串行单连接）。

- 证书：从环境变量 MAIRUI_LICENCE 写 600 临时文件，finally 删除；不打印、不落盘到结果。
- 不重试、不跟随重定向、无代理；STOP/103/429/业务限流 → 写 halted 并整批停。
- 计数账本：/workspace/team/runtime/mairui-batch-T-B140.count（先记账后发请求）。
- 原始数据：/workspace/team/runtime/T-B140-data/（不入仓库）。
用法：tb140_daily_bars.py latest20 | ssjy_all | history --max N [--codes-file F]
"""
from __future__ import annotations

import argparse, json, os, stat, sys, time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

if __package__:
    from . import tb140_history_load as history_load
    from . import tb140_history_backfill as history_backfill
else:
    import tb140_history_load as history_load
    import tb140_history_backfill as history_backfill

HOST = "https://api.mairuiapi.com"
RUNTIME = Path("/workspace/team/runtime")
COUNTER = RUNTIME / "mairui-batch-T-B140.count"
TEMP_SECRET = RUNTIME / "mairui-T-B140.tmp"
STOP = RUNTIME / "mairui-T-B140.STOP"
DATA = RUNTIME / "T-B140-data"
BATCH_CAP = 2000
MST = ZoneInfo("America/Denver")
F20 = ("600519","688018","300364","688073","301218","300477","000520","688130","000972","002598","002535","300497","600606","688110","002726","601611","300250","002719","600818","300474")
HIST_ST, HIST_ET = "20231113", "20261113"


class Halt(Exception):
    pass


def now() -> str:
    return datetime.now(MST).isoformat()


def mkt(code: str) -> str:
    return history_load.market_of(code.strip())


def load_counter() -> dict[str, Any]:
    if COUNTER.exists():
        return json.loads(COUNTER.read_text(encoding="utf-8"))
    return {"schema": "T-B140/v1", "total": 0, "halted": False, "halt_reason": None, "by_kind": {}, "done_history": []}


def save_counter(st: dict[str, Any]) -> None:
    tmp = COUNTER.with_suffix(".count.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
        f.flush(); os.fsync(f.fileno())
    os.replace(tmp, COUNTER)


def write_secret() -> str:
    val = os.environ.get("MAIRUI_LICENCE", "").strip()
    if not val:
        raise Halt("licence_env_missing")
    old = os.umask(0o077)
    try:
        fd = os.open(TEMP_SECRET, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(val)
    finally:
        os.umask(old)
    return TEMP_SECRET.read_text(encoding="utf-8").strip()


def session():
    import requests
    from requests.adapters import HTTPAdapter
    s = requests.Session(); s.trust_env = False; s.proxies = {}
    s.mount("https://", HTTPAdapter(max_retries=0, pool_connections=1, pool_maxsize=1, pool_block=True))
    return s


def biz_limited(body: Any) -> bool:
    txt = json.dumps(body, ensure_ascii=False)[:2000] if not isinstance(body, list) else ""
    return any(k in txt for k in ("限流", "超出", "超过", "频繁", "上限", "次数"))


def call(sess, st, secret, kind, path_tmpl, params=None) -> tuple[int, Any]:
    if STOP.exists():
        raise Halt("STOP")
    if st.get("halted"):
        raise Halt("halted")
    st["total"] += 1
    st["by_kind"][kind] = st["by_kind"].get(kind, 0) + 1
    save_counter(st)  # reserve first
    url = HOST + path_tmpl.replace("{licence}", quote(secret, safe=""))
    try:
        r = sess.get(url, params=params, timeout=(8, 40), allow_redirects=False)
    except Exception:
        st["halted"] = True; st["halt_reason"] = f"transport_failure:{kind}"; save_counter(st)
        raise Halt("transport_failure_no_retry") from None
    status = int(r.status_code)
    try:
        body = r.json() if r.content else None
    except Exception:
        body = {"_non_json": True, "_bytes": len(r.content)}
    if status in (103, 429) or (status != 200 and biz_limited(body)) or (status == 200 and isinstance(body, dict) and biz_limited(body)):
        st["halted"] = True; st["halt_reason"] = f"HTTP_{status}:{kind}"; save_counter(st)
        STOP.write_text(f"{now()} HTTP_{status} {kind}\n")
        raise Halt(f"HTTP_{status}")
    if status != 200:
        st["halted"] = True; st["halt_reason"] = f"HTTP_{status}:{kind}"; save_counter(st)
        raise Halt(f"HTTP_{status}")
    return status, body


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["latest20", "ssjy_all", "history"])
    ap.add_argument("--max", type=int, default=BATCH_CAP)
    ap.add_argument("--codes-file")
    ap.add_argument("--st", default=None)
    ap.add_argument("--et", default=None)
    a = ap.parse_args(argv)
    try:
        start, end = history_load.parse_window(a.st, a.et)
        codes, skipped = (history_load.requestable_history_codes(history_backfill.load_codes(Path(a.codes_file)))
                          if a.mode == "history" else ([], []))
    except (ValueError, TypeError):
        return 1
    DATA.mkdir(parents=True, exist_ok=True)
    st = load_counter()
    summ: dict[str, Any] = {"mode": a.mode, "started_mst": now(), "calls": 0, "halt": None}
    summ["skipped_codes"] = skipped
    secret = ""
    try:
        if st.get("halted"):
            raise Halt("halted_before_start")
        secret = write_secret()
        sess = session()
        if a.mode == "latest20":
            out = DATA / "latest20.jsonl"
            with out.open("a", encoding="utf-8") as f:
                for c in F20:
                    s, b = call(sess, st, secret, "latest", f"/hsstock/latest/{c}.{mkt(c)}/d/n/{{licence}}", {"lt": 1})
                    summ["calls"] += 1
                    f.write(json.dumps({"code": c, "mkt": mkt(c), "at": now(), "status": s, "body": b}, ensure_ascii=False) + "\n")
        elif a.mode == "ssjy_all":
            s, b = call(sess, st, secret, "ssjy_all", "/hsrl/ssjy/all/{licence}")
            summ["calls"] += 1
            (DATA / f"ssjy_all_{datetime.now(MST).strftime('%Y%m%dT%H%M%S')}.json").write_text(json.dumps({"at": now(), "status": s, "body": b}, ensure_ascii=False))
        else:
            summ["expansion_plan"] = history_load.plan_history_expansion(st, ledger_path=COUNTER, st=start, et=end)
            done = set(st.get("done_history") or [])
            todo = [c for c in codes if c not in done][: min(a.max, BATCH_CAP)]
            out = DATA / "history.jsonl"
            with out.open("a", encoding="utf-8") as f:
                for c in todo:
                    s, b = call(sess, st, secret, "history", history_backfill.history_path(c, secret, start, end))
                    summ["calls"] += 1
                    f.write(json.dumps({"code": c, "mkt": mkt(c), "at": now(), "status": s, "n": len(b) if isinstance(b, list) else None, "body": b}, ensure_ascii=False) + "\n")
                    f.flush()
                    if history_load._bj_write_unconfirmed({"code": f"{c}.{mkt(c)}"}):
                        summ.setdefault("blocked_bj_unconfirmed", []).append(c)
                        continue
                    st.setdefault("done_history", []).append(c)
                    st.setdefault("history_windows", {})[c] = {"st": start.isoformat() if start else None, "et": end.isoformat() if end else None}
                    save_counter(st)
            summ["remaining"] = len([c for c in codes if c not in st.get("done_history", [])])
        sess.close()
        return 1 if summ.get("blocked_bj_unconfirmed") else 0
    except Halt as e:
        summ["halt"] = str(e)
        return 1
    finally:
        try:
            TEMP_SECRET.unlink(missing_ok=True)
        except Exception:
            pass
        summ["licence_deleted"] = not TEMP_SECRET.exists()
        summ["total"] = st.get("total"); summ["halted"] = st.get("halted"); summ["finished_mst"] = now()
        txt = json.dumps(summ, ensure_ascii=False)
        txt = history_backfill.redact(txt, secret)
        print(txt)
        with (DATA / "runs.jsonl").open("a") as f:
            f.write(txt + "\n")


if __name__ == "__main__":
    sys.exit(main())
