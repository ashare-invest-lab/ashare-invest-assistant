# S-01 短线·强势股回踩 `st_pullback_ma` — 正式卡 v3（T-R88；v2 为 T-R55；v1 为 T-R25 首次正式化）

> T-R108 历史冻结快照，保留正式卡与策略规格机器块。

```yaml strategy-card
key: st_pullback_ma
version_no: 3
name: 短线·强势股回踩
category: momentum
horizons: [short]
card_id: S-01
risk_level: normal
hypothesis:
  why_it_works: 短期强势、均线多头排列的股票，在缩量回踩 MA10 不破时抛压较轻，趋势容易延续
  falsified_by:
    - 样本外信号后 5 个交易日扣费超额（对所属行业指数）中位数 <= 0
    - 模拟跟踪 n >= 30 后 5 日胜率 < 45%
    - 参数邻域（rs_min ±0.05、shrink_ratio ±0.1）内结论符号翻转
dimensions:
  - {dimension: technical, role: core}
  - {dimension: sector_market, role: veto}
entry:
  - {ref: E1, text: 20 日涨幅达到绝对强势阈值, status: quantified}
  - {ref: E2, text: MA5>MA10>MA20 多头排列, status: quantified}
  - {ref: E3, text: 当日最低回踩 MA10 上方 touch_pct 以内且收盘不破 MA10, status: quantified}
  - {ref: E4, text: 当日成交额低于 5 日均额的 shrink_ratio 倍（缩量）, status: quantified}
counter_evidence:
  - {ref: C1, text: 回踩日单日跌幅大于 5%，可能是出货, status: quantified}
  - {ref: C2, text: 放量回落, status: quantified}
invalidation:
  - {ref: I1, text: MA5 跌破 MA10，多头排列前提消失, status: quantified}
exit:
  - {ref: X1, text: 收盘连续 exit_confirm_days 日低于 MA10（趋势失效）, status: quantified}
  - {ref: X2, text: 收盘跌破入场价 8%（止损类）, status: quantified}
  - {ref: X3, text: 持有满 time_stop 日未达 1R（时间止损）, status: quantified}
data_needs:
  - {feature_key: f.close_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.low_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.amount, frequency: daily, adjust: none, available_at: T 日日线入库后}
  - {feature_key: f.list_days, frequency: daily, adjust: none, available_at: T 日 18:00 主数据后}
  - {feature_key: f.market_regime_idx, frequency: daily, adjust: none, available_at: T 日盘后（沪深300 日线落库后，F50）}
  - {feature_key: f.limit_up_price, frequency: daily, adjust: none, available_at: T 日开盘前（无涨跌幅日为 null）}
  - {feature_key: f.limit_locked_up, frequency: daily, adjust: none, available_at: T 日日线入库后}
  - {feature_key: f.is_suspended, frequency: daily, adjust: none, available_at: T 日日线入库后（sf）}
epistemic:
  hypothesis: hypothesis
  params_schema.rs_min: hypothesis
  params_schema.touch_pct: hypothesis
  params_schema.shrink_ratio: hypothesis
  params_schema.exit_confirm_days: hypothesis
  params_schema.hard_stop_pct: hypothesis
  params_schema.time_stop: hypothesis
  params_schema.min_amount: hypothesis
  params_schema.min_list_days: hypothesis
  params_schema.slippage_bp: estimate
universe:
  pool: 全市场（持仓 ∪ 自选优先）
  boards: {main: true, chinext: true, star: true, bse: false}
  exclude: [ST、停牌、上市不足 min_list_days 由 G-01/F2 处理]
pitfalls:
  - 把下跌趋势中的反弹当作回踩（由 E2 多头排列与 V1 大盘否决防护）
  - 忽略 T+1：入场当天无法止损
  - 用在成交稀少的股票上，成交价远离参考价（由 F1 与冲击成本防护）
a_share_constraints: >-
  沿用 universe 对 ST、停牌的排除；ST/*ST、退市整理阻断买入方向候选信号的执行，持仓退出仍按原规则评估，不以排除买入替代风险监控。
  T+1：当日新买股份不可当日卖出；停牌买卖均不可执行，一字涨停阻买、一字跌停阻卖。
  涨跌停按 config/market_rules.yaml 有效段：主板普通股10%；主板ST/*ST在2026-07-06前5%、当天起10%；创业板/科创板含风险警示20%；北交所含风险警示30%，但本卡仍不含北交所。
  沪深注册制新股前5个交易日、北交所新股首日及退市整理首日按配置不设涨跌幅；2023-04-10前未建模。
  科创板买入至少200股、其余所含板块100股整数倍；科创板1股递增完整依据未验证；零股一次性卖出；原止损价截断口径不变，仅在存在有效涨跌停价时适用。
  参数出处及未验证边界见正文“A 股约束（补充执行口径）”；仅为候选信号，不荐股、不承诺收益。
validation_summary: {type: rule, window: 未执行, benchmark: 所属申万一级行业指数；对照中证全指, cost_model: plan 2.13 默认（含冲击成本分档）, oos_result: 未验证, trade_log_ref: null}
```

```yaml strategy-spec
key: st_pullback_ma
version_no: 3
kind: rule_template
horizons: [short]
params_schema:
  rs_min: {type: float, default: 0.15, min: 0.10, max: 0.30, step: 0.05, desc: 20 日涨幅绝对强势阈值, unit: ratio}
  touch_pct: {type: float, default: 0.01, min: 0.0, max: 0.03, step: 0.005, desc: 回踩触及 MA10 上方容忍带, unit: ratio}
  shrink_ratio: {type: float, default: 0.7, min: 0.5, max: 0.9, step: 0.05, desc: 缩量系数（当日额/5 日均额上限）, unit: ratio}
  exit_confirm_days: {type: int, default: 2, min: 1, max: 3, step: 1, desc: 跌破 MA10 确认天数, unit: 有效日K}
  hard_stop_pct: {type: float, default: 0.08, min: 0.05, max: 0.12, step: 0.01, desc: 硬止损比例, unit: ratio}
  time_stop: {type: int, default: 5, min: 3, max: 10, step: 1, desc: 时间止损天数, unit: 交易日}
  min_amount: {type: float, default: 50000000.0, min: 10000000.0, max: 500000000.0, step: 10000000.0, desc: 20 日均成交额下限, unit: CNY}
  min_list_days: {type: int, default: 60, min: 30, max: 250, step: 10, desc: 上市交易日下限, unit: 交易日}
  slippage_bp: {type: float, default: 10.0, min: 0.0, max: 50.0, step: 1.0, desc: 基础滑点, unit: bp}
rules:
  - {id: E1, dimension: technical, role: entry, weight: 2, eval_time: daily_close, status: quantified,
     expr: "pct_change(f.close_qfq, 20) >= p.rs_min", required_features: [f.close_qfq],
     edge_cases: 有效 K < 21 → insufficient_data}
  - {id: E2, dimension: technical, role: entry, weight: 2, eval_time: daily_close, status: quantified,
     expr: "ma(f.close_qfq, 5) > ma(f.close_qfq, 10) and ma(f.close_qfq, 10) > ma(f.close_qfq, 20)",
     required_features: [f.close_qfq]}
  - {id: E3, dimension: technical, role: entry, weight: 2, eval_time: daily_close, status: quantified,
     expr: "f.low_qfq <= ma(f.close_qfq, 10) * (1 + p.touch_pct) and f.close_qfq >= ma(f.close_qfq, 10)",
     required_features: [f.low_qfq, f.close_qfq]}
  - {id: E4, dimension: technical, role: entry, weight: 1, eval_time: daily_close, status: quantified,
     expr: "f.amount < ma(f.amount, 5) * p.shrink_ratio", required_features: [f.amount]}
  - {id: F1, dimension: technical, role: filter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ma(f.amount, 20) >= p.min_amount", required_features: [f.amount]}
  - {id: F2, dimension: technical, role: filter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.list_days >= p.min_list_days", required_features: [f.list_days]}
  - {id: V1, dimension: sector_market, role: veto, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.market_regime_idx == 'downtrend'", required_features: [f.market_regime_idx]}
  - {id: C1, dimension: technical, role: counter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "pct_change(f.close_qfq, 1) < -0.05", required_features: [f.close_qfq]}
  - {id: C2, dimension: technical, role: counter, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.amount > ma(f.amount, 20) * 1.5", required_features: [f.amount]}
  - {id: I1, dimension: technical, role: invalidation, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ma(f.close_qfq, 5) < ma(f.close_qfq, 10)", required_features: [f.close_qfq]}
  - {id: X1, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.close_qfq < ma(f.close_qfq, 10) for p.exit_confirm_days days", required_features: [f.close_qfq]}
  - {id: X2, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "f.close_qfq <= plan.entry_price_qfq * (1 - p.hard_stop_pct)", required_features: [],
     edge_cases: 买入当日可卖 0，信号照常，执行层记 T1_NOT_SELLABLE}
  - {id: X3, dimension: technical, role: exit, weight: 0, eval_time: daily_close, status: quantified,
     expr: "ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1", required_features: []}
action_map: {entry_all_core_pass: buy, held_hold: hold, exit: sell, else: wait}
stops: {stop_loss: "plan.entry_price_qfq * (1 - p.hard_stop_pct)", take_profit: null, time_stop_days: 5}
dimension_view_thresholds: {bullish: 0.67, bearish: 0.33}
valid_until: {trading_days: 1}
screen: null
```
