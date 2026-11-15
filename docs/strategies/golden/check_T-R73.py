"""T-R73【虚构】离线 golden：独立重算，不导入业务引擎、不生成期望值。

用法：python check_T-R73.py [fixture.json]；失败返回 1，支持 python -O。
"""
from __future__ import annotations

import copy
import json
import math
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import subprocess
import sys
import tempfile


def require(ok, message):
    if not ok:
        raise ValueError(message)


def cents(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), ROUND_HALF_UP))


def yuan(value):
    return float(Decimal(str(value)).quantize(Decimal("1"), ROUND_HALF_UP))


def mean(values):
    return sum(values) / len(values)


def rounded(value, digits=8):
    return None if value is None else round(value, digits)


def factor(case, day, as_of):
    visible = [e for e in case["factor_events"]
               if e["effective_date"] <= day and e["available_at"] <= as_of]
    require(visible, "因子不可见：" + day)
    return max(visible, key=lambda e: e["effective_date"])["A"]


def rsi(values):
    if len(values) < 28:
        return None
    changes = [b - a for a, b in zip(values, values[1:])]
    gain = mean([max(x, 0) for x in changes[:14]])
    loss = mean([max(-x, 0) for x in changes[:14]])
    for x in changes[14:]:
        gain = (13 * gain + max(x, 0)) / 14
        loss = (13 * loss + max(-x, 0)) / 14
    if gain == loss == 0:
        return None
    return round(100 * gain / (gain + loss), 2)


def bandwidth(values):
    middle = mean(values[-20:])
    return round(4 * math.sqrt(mean([(x - middle) ** 2 for x in values[-20:]])) / middle, 6)


def environment(case, day):
    rows = [x for x in case["environment"]["rows"] if x["date"] <= day]
    # 两个指数都重算并返回证据；V1 只使用主基准，不替代行业超额。
    states = {"F25": None, "F50": None}
    previous = {"F25": None, "F50": None}
    evidence = None
    for i in range(59, len(rows)):
        sample = rows[:i + 1]
        require(all(x["available_at"] <= day + "T17:15:00+08:00" for x in sample), "环境输入未定稿")
        idx = [x["primary_close"] for x in sample]
        aux = [x["auxiliary_close"] for x in sample]
        breadth = []
        for row in sample[-20:]:
            eligible = [x for x in row["market"] if not x["is_suspended"] and x["volume"] > 0]
            require(eligible, "宽度无有效样本")
            breadth.append(sum(x["close"] > x["pre_close"] for x in eligible) / len(eligible))
        m20, m60, b20 = mean(idx[-20:]), mean(idx[-60:]), mean(breadth)
        up, down = idx[-1] > m60 and m20 > m60, idx[-1] < m60 and m20 < m60
        raw = {"F50": "uptrend" if up else "downtrend" if down else "range",
               "F25": "uptrend" if up and b20 > .5 else "downtrend" if down and b20 < .4 else "range"}
        for key in states:
            if states[key] is None or previous[key] == raw[key]:
                states[key] = raw[key]
            previous[key] = raw[key]
        evidence = dict(primary_close=idx[-1], primary_ma20=m20, primary_ma60=m60,
                        auxiliary_ma20=mean(aux[-20:]), auxiliary_ma60=mean(aux[-60:]), breadth_ma20=b20,
                        **states)
    require(evidence is not None, "环境预热不足")
    return {k: rounded(v) if isinstance(v, (float, int)) else v for k, v in evidence.items()}


def validate_input(case):
    require(case["label"].startswith("【虚构】"), "缺虚构标签")
    require(case["parameter_status"] == "未验证", "参数须保留未验证")
    require(20 <= len(case["bars"]) <= 60, "主段长度")
    rows = case["warmup_bars"] + case["bars"]
    require([x["date"] for x in rows] == sorted({x["date"] for x in rows}), "日期须唯一有序")
    for b in rows:
        as_of = b["date"] + "T17:15:00+08:00"
        require(b["available_at"] <= as_of, "日线未定稿")
        require(b["A_available_at"] <= as_of, "因子未可见")
        require(b["A"] == factor(case, b["date"], as_of), "A 与可见事件不符")
        require(b["limit_up"] == cents(Decimal(str(b["pre_close"])) * Decimal("1.1")), "涨停价")
        require(b["limit_down"] == cents(Decimal(str(b["pre_close"])) * Decimal("0.9")), "跌停价")
        if b["is_suspended"]:
            require(all(b[k] is None for k in ("open", "high", "low", "close")), "停牌不补价")
            require(b["volume"] == b["amount"] == 0, "停牌无成交")
        else:
            require(all(isinstance(b[k], (float, int)) for k in ("open", "high", "low", "close")), "有效 K 缺价")
            require(b["limit_down"] <= b["low"] <= min(b["open"], b["close"]) <=
                    max(b["open"], b["close"]) <= b["high"] <= b["limit_up"], case["id"] + " " + b["date"] + " OHLC/限价非法")
            require(b["volume"] > 0 and b["amount"] > 0, "无效成交")


def recompute(case, wrong_last_anchor=False):
    validate_input(case)
    bars, warm, p, card = case["bars"], case["warmup_bars"], case["params"], case["card_id"]
    all_rows = warm + bars
    outputs = []
    trade = None
    entry_i = None
    frozen = None
    trigger = None
    for i, b in enumerate(bars):
        as_of = b["date"] + "T17:15:00+08:00"
        upto = all_rows[:len(warm) + i + 1]
        valid = [x for x in upto if not x["is_suspended"]]
        anchor = all_rows[-1]["A"] if wrong_last_anchor else factor(case, b["date"], as_of)
        c = [x["close"] * factor(case, x["date"], as_of) / anchor for x in valid]
        lo = [x["low"] * factor(case, x["date"], as_of) / anchor for x in valid]
        hi = [x["high"] * factor(case, x["date"], as_of) / anchor for x in valid]
        amounts = [x["amount"] for x in valid]
        cal20 = [x for x in upto[-20:] if not x["is_suspended"]]
        adv = mean(amounts[-20:]) if card == "S-01" else (yuan(mean([x["amount"] for x in cal20])) if len(cal20) >= 15 else None)
        metrics = dict(A_T=anchor, close_qfq=None if b["is_suspended"] else c[-1],
                       ma5=mean(c[-5:]), ma10=mean(c[-10:]), ma20=mean(c[-20:]), amount_20d_avg=adv)
        env = environment(case, b["date"])
        rules = {}
        ready = len(valid) >= case["fixed_params"]["warmup"] and not b["is_suspended"]
        # 停牌日仅输出退出指令状态，不重复使用上一根 K 产生候选。
        if card == "S-01":
            momentum = c[-1] / c[-21] - 1 if len(c) >= 21 else None
            a5 = mean(amounts[-5:])
            metrics.update(return20=momentum, amount_5valid_avg=a5, touch_limit=metrics["ma10"] * (1 + p["touch_pct"]))
            rules = dict(E1=momentum is not None and momentum >= p["rs_min"],
                         E2=metrics["ma5"] > metrics["ma10"] > metrics["ma20"],
                         E3=lo[-1] <= metrics["touch_limit"] and c[-1] >= metrics["ma10"],
                         E4=amounts[-1] < a5 * p["shrink_ratio"], F1=adv >= p["min_amount"],
                         F2=b["list_days"] >= p["min_list_days"], V1=env["F50"] == "downtrend",
                         C1=not b["is_suspended"] and b["close"] / b["pre_close"] - 1 < -.05,
                         C2=amounts[-1] > adv * 1.5, I1=metrics["ma5"] < metrics["ma10"])
        elif card == "S-02":
            recent = [rsi(c[:len(c) - j]) for j in (2, 1, 0)]
            ret = c[-1] / c[-6] - 1 if len(c) >= 6 else None
            metrics.update(rsi14=recent[-1], recent_rsi14=recent, return5=ret, previous_high_qfq=hi[-2], low5_qfq=min(lo[-5:]))
            rules = dict(E1=any(x is not None and x < p["rsi_os"] for x in recent),
                         E2=ret is not None and ret <= -p["drop_5d"], E3=c[-1] > hi[-2],
                         F1=adv is not None and adv >= p["min_amount"] and b["list_days"] >= p["min_list_days"],
                         V1=env["F25"] == "downtrend", C1=c[-1] < c[-2] and adv is not None and amounts[-1] > adv * 1.5,
                         I1=c[-1] < min(lo[-6:-1]))
        elif card == "S-04":
            count = sum(x["close"] == x["limit_up"] for x in cal20) if len(cal20) >= 15 else None
            previous_rows = upto[-3:]
            seal2 = len(previous_rows) == 3 and not previous_rows[0]["is_suspended"] and previous_rows[0]["close"] == previous_rows[0]["limit_up"]
            broken = len(previous_rows) == 3 and not previous_rows[1]["is_suspended"] and previous_rows[1]["close"] != previous_rows[1]["limit_up"]
            metrics.update(limit_up_count20=count, previous_high_qfq=hi[-2])
            rules = dict(E1=seal2 and broken and count is not None and count >= p["min_boards"],
                         E2=c[-1] > hi[-2], E3=adv is not None and amounts[-1] > adv * p["vol_ratio"],
                         V1=env["F25"] == "downtrend", C1=not b["is_suspended"] and b["close"] == b["limit_up"],
                         I1=c[-1] < hi[-3] and c[-2] < hi[-4])
        else:
            widths = [bandwidth(c[:j]) for j in range(20, len(c) + 1)][-120:]
            bw = widths[-1]
            rank = (sum(x < bw for x in widths) + (sum(x == bw for x in widths) + 1) / 2) / len(widths) if len(widths) >= 90 else None
            rank = rounded(rank, 4)
            level = max(c[-21:-1])
            metrics.update(boll_bw20=bw, bw_pct120=rank, bandwidth_values=len(widths), breakout20_qfq=level)
            rules = dict(E1=rank is not None and rank <= p["bw_pct120_th"], E2=c[-1] > level,
                         E3=adv is not None and amounts[-1] >= adv * p["vol_mult"],
                         F1=adv is not None and adv >= p["min_amount"], F2=b["list_days"] >= p["min_list_days"],
                         V1=env["F25"] == "downtrend", C1=not b["is_suspended"] and b["close"] / b["pre_close"] - 1 > .095,
                         I1=None)
        if b["is_suspended"]:
            rules = {key: None for key in rules}
        candidate = (ready and b["close"] >= 2 and b["list_days"] >= case["fixed_params"]["min_list_days"]
                     and all(v for k, v in rules.items() if k.startswith(("E", "F"))) and not rules["V1"])
        exits = {}
        # 开盘先处理昨天已发出的退出指令，绝不使用当天收盘确认开盘成交。
        if trade and entry_i is not None and trigger is not None and trade["exit_date"] is None and i > trigger:
            reason = "SUSPENDED" if b["is_suspended"] else "LIMIT_LOCKED" if b["open"] == b["limit_down"] else "T1_NOT_SELLABLE" if i <= entry_i or not b["sellable_at_open"] else None
            if reason:
                trade["execution_blocks"].append(dict(date=b["date"], reason=reason))
            else:
                trade.update(exit_date=b["date"], exit_price_raw=b["open"], stop_execution_date=b["date"] if frozen else None,
                             exit_after_base_slippage=b["open"] * (1 - p["slippage_bp"] / 10000))
        if trade and entry_i is not None and i >= entry_i and trade["exit_date"] is None and not b["is_suspended"]:
            cost = trade["entry_price_raw"] * factor(case, trade["entry_date"], as_of) / anchor
            age = i - entry_i  # 本 fixture 明示的未验证计日约定；不作为策略裁定。
            below2 = all(c[-1-j] < mean(c[-10-j:len(c)-j if j else None]) for j in range(2))
            metrics["entry_price_qfq"] = cost
            if frozen:
                threshold = frozen["L_raw"] * factor(case, frozen["s"], as_of) / anchor
                if card == "W-02":
                    threshold *= 1 - p["fail_pct"]
                metrics["structure_threshold_qfq"] = threshold
            if card == "S-01":
                exits = dict(X1=below2, X2=c[-1] <= cost * (1 - p["hard_stop_pct"]), X3=None if age >= p["time_stop"] else False)
            elif card == "S-02":
                exits = dict(X1=c[-1] <= cost * (1-p["stop_pct"]), X2=c[-1] >= cost * (1+p["tp_pct"]),
                             X3=rsi(c) is not None and rsi(c) > p["rsi_exit"] and c[-1] < c[-2], X4=age >= p["max_hold"], X1b=c[-1] < threshold)
            elif card == "S-04":
                exits = dict(X1=c[-1] <= cost * (1-p["stop_pct"]), X2=c[-1] < metrics["ma5"], X3=age >= p["max_hold"], X1b=c[-1] < threshold)
            else:
                exits = dict(X1=c[-1] <= cost * (1-p["stop_pct"]), X2=below2, X3=age >= p["max_hold"],
                             X4=None if age >= 3 else False, X5=c[-1] < threshold)
            hit = [k for k, v in exits.items() if v is True]
            if trigger is None and hit:
                trigger = i
                trade.update(exit_signal_date=b["date"], exit_reasons=hit,
                             stop_trigger_date=b["date"] if frozen and exits["X5" if card == "W-02" else "X1b"] else None)
        if candidate and trade is None:
            signal_day = b["date"]
            if card != "S-01":
                level = min(lo[-5:]) if card == "S-02" else hi[-2] if card == "S-04" else max(c[-21:-1])
                frozen = dict(L_raw=level, s=signal_day)
            nxt = bars[i+1] if i+1 < len(bars) else None
            require(nxt is not None and not nxt["is_suspended"] and nxt["open"] < nxt["limit_up"], "fixture 入场不可成交")
            entry_i = i + 1
            trade = dict(signal_date=signal_day, entry_date=nxt["date"], entry_price_raw=nxt["open"], frozen_structure=frozen,
                         exit_signal_date=None, exit_date=None, exit_price_raw=None, exit_reasons=[], stop_trigger_date=None,
                         stop_execution_date=None, execution_blocks=[], exit_after_base_slippage=None, impact_cost=None, fees=None)
        outputs.append(dict(date=b["date"], candidate=bool(candidate), ready=ready,
                            rules=rules, triggered_conditions=[k for k, v in rules.items() if v is True],
                            exit_rules=exits, metrics={k: [rounded(x) for x in v] if isinstance(v, list) else rounded(v) for k, v in metrics.items()},
                            environment=env))
    return dict(daily=outputs, trade=trade)


def compare(actual, expected, path="expect"):
    if isinstance(expected, dict):
        require(isinstance(actual, dict) and actual.keys() == expected.keys(), path + ": 字段不同")
        for key in expected:
            compare(actual[key], expected[key], path + "." + key)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), path + ": 长度不同")
        for i, (a, e) in enumerate(zip(actual, expected)):
            compare(a, e, path + f"[{i}]")
    elif type(expected) in (float, int):
        require(type(actual) in (float, int) and math.isclose(actual, expected, abs_tol=1e-7, rel_tol=1e-10), f"{path}: {actual!r} != {expected!r}")
    else:
        require(type(actual) is type(expected) and actual == expected, f"{path}: {actual!r} != {expected!r}")


def validate(data, wrong_last_anchor=False):
    require(data["label"].startswith("【虚构】"), "数据必须标虚构")
    require({c["card_id"] for c in data["cases"]} == {"S-01", "S-02", "S-04", "W-02"}, "四卡覆盖")
    for case in data["cases"]:
        computed = recompute(case, wrong_last_anchor)
        # 先报告执行账本差异，让移除停牌负例直接定位最早成交日改变。
        compare(computed["trade"], case["expect"]["trade"], case["id"] + ".trade")
        compare(computed, case["expect"], case["id"])


def check_regenerated(path):
    """L-042 合成 golden 豁免：gen_T-R73.py 重新生成的内容必须与提交内容逐字节一致。"""
    gen = Path(__file__).with_name("gen_T-R73.py")
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run([sys.executable, str(gen), tmp], capture_output=True, text=True)
        if proc.returncode != 0:
            raise ValueError("生成脚本失败：" + proc.stderr.strip()[-300:])
        if (Path(tmp) / "T-R73_golden.json").read_bytes() != path.read_bytes():
            raise ValueError("重新生成的 golden 与提交内容不一致")


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("T-R73_golden.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    validate(data)
    regen_checked = len(sys.argv) <= 1
    if regen_checked:
        check_regenerated(path)
    price = copy.deepcopy(data)
    price["cases"][0]["bars"][30]["close"] -= .01
    suspension = copy.deepcopy(data)
    b = suspension["cases"][1]["bars"][34]
    b.update(is_suspended=False, open=8.94, high=9.0, low=8.9, close=8.94, volume=10000000, amount=100000000)
    rejected = []
    for name, mutated, wrong in (("price", price, False), ("remove_suspension", suspension, False), ("last_day_qfq_anchor", data, True)):
        try:
            validate(mutated, wrong)
        except ValueError as exc:
            rejected.append(dict(name=name, diagnostic=str(exc)))
        else:
            raise ValueError("篡改负例被接受：" + name)
    print(json.dumps(dict(result="PASS", regenerated_identical=regen_checked, cases=len(data["cases"]), daily_rows=sum(len(c["bars"]) for c in data["cases"]),
                          negative_mutations_rejected=rejected), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
        print("FAIL: " + str(error), file=sys.stderr)
        sys.exit(1)
