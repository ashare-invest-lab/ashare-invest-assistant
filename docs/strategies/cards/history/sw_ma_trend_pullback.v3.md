# W-01 波段·均线趋势回踩 `sw_ma_trend_pullback` — 正式卡 v3（T-R88；v2 为 T-R20；v1 为 T-R15）

> T-R108 历史冻结快照，保留正式卡与策略规格机器块。

```yaml strategy-card
key: sw_ma_trend_pullback
version_no: 3
name: 波段·均线趋势回踩
category: trend
horizons: [swing]
card_id: W-01
risk_level: normal
hypothesis:
  why_it_works: 中期趋势存在惯性；趋势中的回踩不破提供止损距离较近的跟随点
  falsified_by:
    - 研究侧：样本外信号后 20 个交易日扣费超额收益（对所属申万一级行业指数）中位数 ≤ 0
    - 研究侧：参数邻域（ma_fast ±5、pullback_pct ±0.01）内扣费超额符号翻转
    - 模拟跟踪：n ≥ 30 时 5 日胜率 < 45% 且平均超额 < 0
dimensions:
  - {dimension: technical, role: core}
  - {dimension: capital, role: auxiliary}
  - {dimension: fundamental, role: veto}
  - {dimension: sentiment, role: veto}
  - {dimension: sector_market, role: veto}
entry:
  - {ref: E1, text: 20 日均线连续 N 根有效日 K 高于 60 日均线, status: quantified}
  - {ref: E2, text: 近 3 日最低价回到 20 日均线上方 pullback_pct 以内且收盘仍在均线上方, status: quantified}
  - {ref: E3, text: 收盘距 60 日最高收盘回撤不超过 max_dd_from_high, status: quantified}
counter_evidence:
  - {ref: C2, text: 近 20 日主力资金净流出, status: quantified}
  - {ref: C3, text: 当日成交额不足 20 日均额一半, status: quantified}
invalidation:
  - {ref: I1, text: 20 日均线跌破 60 日均线, status: quantified}
  - {ref: I2, text: 大盘环境转为下行, status: quantified}
exit:
  - {ref: X2, text: 盘中触及计划止损价（止损类；买入当日由 T1_NOT_SELLABLE 阻断执行）, status: quantified}
  - {ref: X1, text: 收盘连续 exit_confirm_days 日低于 20 日均线, status: quantified}
  - {ref: X4, text: 收盘跌破前 20 日最低价（结构止损）, status: quantified}
  - {ref: X3, text: 持有满 time_stop 日仍未达 1R（时间止损）, status: quantified}
  - {ref: X6, text: 收盘（qfq@T）跌破止损价 max2(建仓价 qfq − atr_mult×ATR14, 前 20 日最低价)（止损类）, status: quantified}
  - {ref: X5, text: 达到 trail_trigger_r R 后收盘跌破入场以来最高收盘 − trail_atr_mult×ATR14（跟踪止盈，入场以来最高收盘按 qfq@T 折算）, status: quantified}
data_needs:
  - {feature_key: f.close_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.high_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.low_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.amount, frequency: daily, adjust: none, available_at: T 日日线入库后}
  - {feature_key: f.list_days, frequency: daily, adjust: none, available_at: T 日开盘前}
  - {feature_key: f.limit_up_price, frequency: daily, adjust: none, available_at: T 日开盘前（无涨跌幅日为 null）}
  - {feature_key: f.limit_down_price, frequency: daily, adjust: none, available_at: T 日开盘前（无涨跌幅日为 null）}
  - {feature_key: f.is_suspended, frequency: daily, adjust: none, available_at: T 日日线入库后（sf）}
  - {feature_key: f.limit_locked_up, frequency: daily, adjust: none, available_at: T 日日线入库后}
  - {feature_key: f.rsi14, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.main_net_20d, frequency: daily, adjust: none, available_at: T 日盘后（待T003验证）}
  - {feature_key: f.np_yoy_latest, frequency: quarterly, adjust: none, available_at: plrq 次一交易日 09:30}
  - {feature_key: f.market_regime_idx, frequency: daily, adjust: none, available_at: T 日盘后（沪深300 日线落库后，F50）}
epistemic:
  hypothesis: hypothesis
  params_schema.ma_fast: hypothesis
  params_schema.ma_slow: hypothesis
  params_schema.trend_days: hypothesis
  params_schema.pullback_pct: hypothesis
  params_schema.max_dd_from_high: hypothesis
  params_schema.exit_confirm_days: hypothesis
  params_schema.atr_mult: hypothesis
  params_schema.time_stop: hypothesis
  params_schema.trail_trigger_r: hypothesis
  params_schema.trail_atr_mult: hypothesis
  params_schema.rsi_overheat: hypothesis
  params_schema.np_yoy_floor: hypothesis
  params_schema.min_amount: hypothesis
  params_schema.min_list_days: hypothesis
  params_schema.min_edge_cost_mult: hypothesis
  params_schema.slippage_bp: estimate
  params_schema.fixed_cost_bp: estimate
  costs.impact_tiers: estimate
universe:
  pool: 持仓 ∪ 自选
  boards: {main: true, chinext: true, star: true, bse: false}
  security_types: [stock]
applicability: {market_regime: [uptrend, range]}
pitfalls:
  - 把下跌趋势中的反弹当回踩（E1、V1 防护）
  - 忽略 T+1：入场当日无法止损
  - 低波动个股的一倍 ATR 覆盖不了往返成本（F3 防护）
  - 一字涨停时规则满足但不可成交（G-01 LIMIT_LOCKED）
costs:
  commission: 用户费率；未导入时默认估算，单笔最低 5 元
  stamp_duty_sell: 0.0005
  transfer_fee: 0.00001
  slippage_bp: 10
  impact_adv_days: 20
  max_participation_pct: 0.02
  impact_tiers: [{max_r: 0.001, bp: 0}, {max_r: 0.005, bp: 5}, {max_r: 0.01, bp: 15}, {max_r: 0.02, bp: 30}, {max_r: null, bp: 60, flag: 容量受限}]
a_share_constraints: >-
  ST/*ST、退市整理、停牌仍由 G-01 处理；ST/*ST、退市整理阻断买入方向候选信号的执行，持仓退出仍按原规则评估。
  T+1：当日新买股份不可当日卖出；停牌买卖均不可执行，一字涨停阻买、一字跌停阻卖。
  涨跌停按 config/market_rules.yaml 有效段：主板普通股10%；主板ST/*ST在2026-07-06前5%、当天起10%；创业板/科创板含风险警示20%；北交所含风险警示30%，但本卡仍不含北交所。
  沪深注册制新股前5个交易日、北交所新股首日及退市整理首日按配置不设涨跌幅；2023-04-10前未建模。
  科创板买入至少200股、其余所含板块100股整数倍；科创板1股递增完整依据未验证；零股一次性卖出；原止损价截断口径不变，仅在存在有效涨跌停价时适用。
  参数出处及未验证边界见正文“A 股约束（补充执行口径）”；仅为候选信号，不荐股、不承诺收益。
validation_summary: {type: rule, window: 未执行, benchmark: 所属申万一级行业指数；对照中证全指, cost_model: plan 2.13 默认（含冲击成本分档）, oos_result: 未验证, trade_log_ref: null}
fit: {effort: low, risk_tolerance_min: 3, experience_min: novice}
```

```yaml strategy-spec
key: sw_ma_trend_pullback
version_no: 3
kind: rule_template
horizons: [swing]
params_schema:
  ma_fast: {type: int, default: 20, min: 10, max: 30, step: 1, desc: 快均线周期, unit: 有效日K}
  ma_slow: {type: int, default: 60, min: 40, max: 120, step: 5, desc: 慢均线周期, unit: 有效日K}
  trend_days: {type: int, default: 5, min: 3, max: 20, step: 1, desc: 趋势持续根数, unit: 有效日K}
  pullback_pct: {type: float, default: 0.02, min: 0.005, max: 0.05, step: 0.005, desc: 回踩距 MA20 容忍比例}
  max_dd_from_high: {type: float, default: 0.15, min: 0.05, max: 0.25, step: 0.01, desc: 距 60 日最高收盘最大回撤}
  exit_confirm_days: {type: int, default: 2, min: 1, max: 5, step: 1, desc: 跌破 MA20 确认根数, unit: 有效日K}
  atr_mult: {type: float, default: 2.0, min: 1.0, max: 4.0, step: 0.5, desc: ATR 止损倍数}
  time_stop: {type: int, default: 40, min: 10, max: 60, step: 5, desc: 时间止损持有日数, unit: 交易日}
  trail_trigger_r: {type: float, default: 2.0, min: 1.0, max: 4.0, step: 0.5, desc: 启动跟踪止盈的 R 倍数}
  trail_atr_mult: {type: float, default: 2.0, min: 1.0, max: 4.0, step: 0.5, desc: 跟踪止盈 ATR 倍数}
  rsi_overheat: {type: float, default: 75.0, min: 65.0, max: 85.0, step: 1.0, desc: RSI14 过热否决阈值}
  np_yoy_floor: {type: float, default: -30.0, min: -80.0, max: 0.0, step: 5.0, desc: 净利同比否决下限, unit: "%"}
  min_amount: {type: float, default: 50000000.0, min: 10000000.0, max: 500000000.0, step: 10000000.0, desc: 20 日均成交额下限, unit: 元}
  min_list_days: {type: int, default: 120, min: 60, max: 250, step: 10, desc: 最少上市交易日数, unit: 交易日}
  slippage_bp: {type: float, default: 10.0, min: 0.0, max: 50.0, step: 1.0, desc: 单边基础滑点, unit: bp}
  fixed_cost_bp: {type: float, default: 8.0, min: 5.0, max: 30.0, step: 1.0, desc: 往返固定费率近似, unit: bp, user_editable: false}
  min_edge_cost_mult: {type: float, default: 3.0, min: 1.0, max: 10.0, step: 0.5, desc: ATR 相对往返成本的最小倍数}
rules:
  - {id: E1, dimension: technical, role: entry, weight: 2, eval_time: daily_close, expr: "ma(f.close_qfq, p.ma_fast) > ma(f.close_qfq, p.ma_slow) for p.trend_days days", required_features: [f.close_qfq]}
  - {id: E2, dimension: technical, role: entry, weight: 2, eval_time: daily_close, expr: "lowest(f.low_qfq, 3) <= ma(f.close_qfq, p.ma_fast) * (1 + p.pullback_pct) and f.close_qfq > ma(f.close_qfq, p.ma_fast)", required_features: [f.low_qfq, f.close_qfq]}
  - {id: E3, dimension: technical, role: entry, weight: 1, eval_time: daily_close, expr: "f.close_qfq >= highest(f.close_qfq, 60) * (1 - p.max_dd_from_high)", required_features: [f.close_qfq]}
  - {id: A1, dimension: capital, role: entry, weight: 1, core: false, eval_time: daily_close, expr: "f.main_net_20d > 0", required_features: [f.main_net_20d], missing_policy: dimension_unknown}
  - {id: F1, dimension: technical, role: filter, weight: 0, eval_time: daily_close, expr: "ma(f.amount, 20) >= p.min_amount", required_features: [f.amount]}
  - {id: F2, dimension: technical, role: filter, weight: 0, eval_time: daily_close, expr: "f.list_days >= p.min_list_days", required_features: [f.list_days]}
  - {id: F3, dimension: technical, role: filter, weight: 0, eval_time: daily_close, expr: "atr(14) / f.close_qfq * 10000 >= p.min_edge_cost_mult * (2 * p.slippage_bp + p.fixed_cost_bp)", required_features: [f.high_qfq, f.low_qfq, f.close_qfq]}
  - {id: V1, dimension: sector_market, role: veto, weight: 0, eval_time: daily_close, expr: "f.market_regime_idx == 'downtrend'", required_features: [f.market_regime_idx], missing_policy: veto_unknown}
  - {id: V2, dimension: fundamental, role: veto, weight: 0, eval_time: daily_close, expr: "f.np_yoy_latest < p.np_yoy_floor", required_features: [f.np_yoy_latest], missing_policy: veto_unknown}
  - {id: V4, dimension: sentiment, role: veto, weight: 0, eval_time: daily_close, expr: "f.rsi14 > p.rsi_overheat", required_features: [f.rsi14], missing_policy: veto_unknown}
  - {id: C2, dimension: capital, role: counter, weight: 0, eval_time: daily_close, expr: "f.main_net_20d < 0", required_features: [f.main_net_20d]}
  - {id: C3, dimension: technical, role: counter, weight: 0, eval_time: daily_close, expr: "f.amount < ma(f.amount, 20) * 0.5", required_features: [f.amount]}
  - {id: I1, dimension: technical, role: invalidation, weight: 0, eval_time: daily_close, expr: "ma(f.close_qfq, p.ma_fast) < ma(f.close_qfq, p.ma_slow)", required_features: [f.close_qfq]}
  - {id: I2, dimension: sector_market, role: invalidation, weight: 0, eval_time: daily_close, expr: "f.market_regime_idx == 'downtrend'", required_features: [f.market_regime_idx]}
  - {id: X1, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "f.close_qfq < ma(f.close_qfq, p.ma_fast) for p.exit_confirm_days days", required_features: [f.close_qfq]}
  - {id: X2, dimension: technical, role: exit, weight: 0, eval_time: intraday_1m, expr: "ctx.last_price <= plan.stop_loss", required_features: []}
  - {id: X3, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "ctx.holding_days >= p.time_stop and ctx.max_r_reached < 1", required_features: []}
  - {id: X4, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "f.close_qfq < lowest(ref(f.low_qfq, 1), 20)", required_features: [f.close_qfq, f.low_qfq]}
  - {id: X5, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "ctx.max_r_reached >= p.trail_trigger_r and f.close_qfq < ctx.highest_close_since_entry_qfq - p.trail_atr_mult * atr(14)", required_features: [f.close_qfq, f.high_qfq, f.low_qfq]}
  - {id: X6, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "f.close_qfq <= max2(plan.entry_price_qfq - p.atr_mult * atr(14), lowest(ref(f.low_qfq, 1), 20))", required_features: [f.close_qfq, f.high_qfq, f.low_qfq]}
action_map: {entry_all_core_pass: buy, held_hold: hold, exit: sell, else: wait}
stops: {stop_loss: "max2(plan.entry_price_qfq - p.atr_mult * atr(14), lowest(ref(f.low_qfq, 1), 20))", take_profit: null, time_stop_days: 40}
dimension_view_thresholds: {bullish: 0.67, bearish: 0.33}
applicability: {market_regime: [uptrend, range]}
valid_until: {trading_days: 5}
screen: null
```
