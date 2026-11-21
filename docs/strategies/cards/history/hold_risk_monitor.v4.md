# H-01 持仓风险体检 `hold_risk_monitor` — 正式卡 v4（T-R88；v3 为 T-R49；v2 为 T-R20，v1 为 T-R15，纯离场系统组件）

> T-R108 历史冻结快照，保留正式卡与策略规格机器块。

```yaml strategy-card
key: hold_risk_monitor
version_no: 4
name: 持仓风险体检
category: risk
horizons: [intraday_t, short, swing, long]
card_id: H-01
mount_policy: system_only
risk_level: normal
hypothesis:
  why_it_works: 跌破成本缓冲、跌破长期均线是可检验的持仓风险上升提示；单只与行业仓位上限是组合风险限额（阈值属 estimate），不是可检验的收益或亏损预测机制
  falsified_by:
    - F1 模拟跟踪：X2 离场首日后，按 RC5 口径 B 周期 h∈{1,5,20}（缺 horizon 记 gap 不计入），继续持有收益 D 的中位数 ≥ 往返成本中位数，且单侧精确符号检验经 BH 校正 q ≤ 0.10（不重叠事件 n ≥ 30；口径见正文「证伪口径（v4）」F1）
    - F2 模拟跟踪：W1 转弱首日后，相对当日其他持仓等权池（非沪深300）的超额 AR 中位数 ≥ 0，且单侧符号检验不能显示 P(AR<0) > 0.5（α=0.05；不重叠事件 n ≥ 30；h 同 F1；口径见正文「证伪口径（v4）」F2）
dimensions:
  - {dimension: technical, role: core}
  - {dimension: sector_market, role: auxiliary}
counter_evidence:
  - {ref: C1, text: 大盘环境为 uptrend, status: quantified}
  - {ref: C2, text: 收盘仍在 20 日均线上方, status: quantified}
invalidation:
  - {ref: I1, text: 收盘连续 reclaim_days 日重新站上长期均线, status: quantified}
exit:
  - {ref: X1, text: 盘中触及计划止损价（止损类）, status: quantified}
  - {ref: X2, text: 收盘（qfq）跌破摊薄成本（qfq）− cost_atr_k×ATR14（止损类）, status: quantified}
  - {ref: W1, text: 收盘连续 ma_break_days 日低于长期均线（转弱）, status: quantified}
  - {ref: W2, text: 单只仓位占比超过 single_cap（转弱）, status: quantified}
  - {ref: W3, text: 行业仓位占比超过 sector_cap（转弱）, status: quantified}
data_needs:
  - {feature_key: f.close_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.high_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.low_qfq, frequency: daily, adjust: qfq, available_at: T 日日线入库后}
  - {feature_key: f.is_suspended, frequency: daily, adjust: none, available_at: T 日日线入库后（sf）}
  - {feature_key: f.market_regime_idx, frequency: daily, adjust: none, available_at: T 日盘后（沪深300 日线落库后，F50）}
  - {feature_key: f.limit_down_price, frequency: daily, adjust: none, available_at: T 日开盘前（无涨跌幅日为 null）}
  - {feature_key: f.limit_locked_down, frequency: daily, adjust: none, available_at: T 日日线入库后}
epistemic:
  hypothesis: hypothesis
  params_schema.cost_atr_k: hypothesis
  params_schema.ma_long: hypothesis
  params_schema.ma_break_days: hypothesis
  params_schema.reclaim_days: hypothesis
  params_schema.single_cap: estimate
  params_schema.sector_cap: estimate
universe:
  pool: 持仓
  boards: {main: true, chinext: true, star: true, bse: false}
  security_types: [stock]
pitfalls:
  - 通用规则不知道用户原投资逻辑，可能与中长线卡相反——并列展示
  - 一字跌停时卖出信号可能无法成交
  - 当日买入部分 T+1 不可卖
costs:
  stamp_duty_sell: 0.0005
  transfer_fee: 0.00001
  slippage_bp: 10
  impact_adv_days: 20
  max_participation_pct: 0.02
  impact_tiers: [{max_r: 0.001, bp: 0}, {max_r: 0.005, bp: 5}, {max_r: 0.01, bp: 15}, {max_r: 0.02, bp: 30}, {max_r: null, bp: 60, flag: 容量受限}]
a_share_constraints: >-
  本卡仅对持仓产生 reduce/sell 候选信号，不新增买入或加仓；ST/*ST、退市整理不自动取消持仓退出评估，也不单凭风险警示身份触发卖出。
  T+1：当日新买股份不可当日卖出；停牌买卖均不可执行，一字涨停阻买、一字跌停阻卖。
  涨跌停按 config/market_rules.yaml 有效段：主板普通股10%；主板ST/*ST在2026-07-06前5%、当天起10%；创业板/科创板含风险警示20%；北交所含风险警示30%，但本卡仍不含北交所。
  沪深注册制新股前5个交易日、北交所新股首日及退市整理首日按配置不设涨跌幅；2023-04-10前未建模。
  科创板零股（不足200股）一次性卖出；原止损价截断口径不变，仅在存在有效涨跌停价时适用。
  参数出处及未验证边界见正文“A 股约束（补充执行口径）”；仅为候选信号，不荐股、不承诺收益。
validation_summary: {type: rule, window: 未执行, benchmark: 继续持有, cost_model: plan 2.13 默认, oos_result: 未验证, trade_log_ref: null}
```

```yaml strategy-spec
key: hold_risk_monitor
version_no: 4
kind: rule_template
horizons: [intraday_t, short, swing, long]
params_schema:
  ma_long: {type: int, default: 60, min: 40, max: 120, step: 5, desc: 长期均线周期, unit: 有效日K}
  ma_break_days: {type: int, default: 3, min: 2, max: 5, step: 1, desc: 跌破长期均线确认根数, unit: 有效日K}
  reclaim_days: {type: int, default: 2, min: 1, max: 5, step: 1, desc: 重新站上长期均线确认根数, unit: 有效日K}
  cost_atr_k: {type: float, default: 2.0, min: 1.0, max: 4.0, step: 0.5, desc: 成本缓冲 ATR 倍数}
  single_cap: {type: float, default: 0.20, min: 0.05, max: 0.50, step: 0.05, desc: 单只仓位上限（0–1）}
  sector_cap: {type: float, default: 0.40, min: 0.20, max: 0.80, step: 0.05, desc: 行业仓位上限（0–1）}
rules:
  - {id: X1, dimension: technical, role: exit, weight: 0, eval_time: intraday_1m, expr: "ctx.last_price <= plan.stop_loss", required_features: []}
  - {id: X2, dimension: technical, role: exit, weight: 0, eval_time: daily_close, expr: "f.close_qfq < ctx.cost_price_qfq - p.cost_atr_k * atr(14)", required_features: [f.close_qfq, f.high_qfq, f.low_qfq]}
  - {id: W1, dimension: technical, role: weakening, weight: 0, eval_time: daily_close, expr: "f.close_qfq < ma(f.close_qfq, p.ma_long) for p.ma_break_days days", required_features: [f.close_qfq]}
  - {id: W2, dimension: technical, role: weakening, weight: 0, eval_time: daily_close, expr: "ctx.position_weight > p.single_cap", required_features: []}
  - {id: W3, dimension: sector_market, role: weakening, weight: 0, eval_time: daily_close, expr: "ctx.sector_weight > p.sector_cap", required_features: []}
  - {id: C1, dimension: sector_market, role: counter, weight: 0, eval_time: daily_close, expr: "f.market_regime_idx == 'uptrend'", required_features: [f.market_regime_idx]}
  - {id: C2, dimension: technical, role: counter, weight: 0, eval_time: daily_close, expr: "f.close_qfq > ma(f.close_qfq, 20)", required_features: [f.close_qfq]}
  - {id: I1, dimension: technical, role: invalidation, weight: 0, eval_time: daily_close, expr: "f.close_qfq > ma(f.close_qfq, p.ma_long) for p.reclaim_days days", required_features: [f.close_qfq]}
action_map: {exit: sell, weakening: reduce, held_hold: hold, else: hold}
stops: {stop_loss: null, take_profit: null, time_stop_days: null}
dimension_view_thresholds: {bullish: 0.67, bearish: 0.33}
valid_until: {trading_days: 1}
screen: null
```
