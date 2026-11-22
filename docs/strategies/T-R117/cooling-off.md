# T-R117 冷静期规则依据

- lifecycle: draft
- G7: ☐

本文只审查用户本人可见的成交、持仓、计划记录和已出候选信号。冷静期是用户自我约束工具，不荐股，也不承诺收益。主线契约目标与 `origin/main` 的代码现状分开记录。

## 规则依据表

| 触发条件或参数 | 现值（路径:行号；主线未实现写“未实现”） | 公开研究/监管/同类产品做法（真实 URL，状态码见报告） | 结论（有据 / 机制有据数值未验证 / 仓内定义 / 未验证） | 建议默认（开/关、取值） |
|---|---|---|---|---|
| 连续亏损。本人账户按证券逐段平仓，`pnl<0` 连续达到 `closed_loss_streak` 才产生候选暂停。 | `rc5_loss_streak_drawdown.enabled=true`、`closed_loss_streak=3`；`origin/main:config/risk_controls.yaml:23-24`；计算使用可见成交与证据，`origin/main:src/backend/app/feedback/core.py:229-241` | Barber、Odean 的个人账户研究讨论过度交易与表现关系，https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/individual_investor_performance_final.pdf?date=2024-05-08；没有证明三笔阈值。 | 机制有据，数值未验证 | 维持现值（开），数值未验证，改默认须用户拍板 |
| 自高点回撤。本人账户净值从已见峰值到当前点的回撤达到阈值，必须有完整历史。 | `drawdown_from_peak_pct=10`；`origin/main:config/risk_controls.yaml:25`；只取 `at` 与 `available_at` 均不晚于评估时点的净值，`origin/main:src/backend/app/feedback/core.py:257-292` | 监管投资者教育提醒不要因短期波动仓促改变计划，但未规定个人账户百分比阈值，https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-72。 | 机制有据，数值未验证 | 维持现值（开），数值未验证，改默认须用户拍板 |
| 违反自身计划。仅核对本人有效计划与本人实际成交的方向、数量和生效区间。 | `rc6_plan_violation.enabled=true`；checks 为 `opposite_side, qty_over_plan, held_after_invalidation, buy_without_stop, buy_during_wait`；`origin/main:config/risk_controls.yaml:35-36`；已有时点筛选，`origin/main:src/backend/app/feedback/plans.py:152-186`；主线 `SUPPORTED` 仅接通 `opposite_side`、`qty_over_plan`，其余三项产生 `plan_check_not_connected` 缺口。 | MoneySense 建议把投资政策写成可复核的条件式计划并在重大改变前暂停，https://www.moneysense.gov.sg/investments/behavioural-science-and-investing/。该建议面向个人教育，不是证券监管阈值。 | 仓内定义 | 维持现值（开），数值未验证，改默认须用户拍板 |
| 情绪化频繁交易。候选定义为本人单个北京时间交易日的成交笔数或成交额换手超过预先冻结阈值，并记录同日买卖。 | 未实现。现有 `trades` 事实字段可供统计，`origin/main:docs/plan.md:1691`；无确定性阈值、事件原因或冷静状态字段。 | SEC 将 active trading、noise trading 和处置效应列为可能损害表现的行为，https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-72；FINRA 说明频繁日内交易的成本和风险，https://syndication.finra.org/content/frequent-intraday-trading-understanding-basics。两者约束券商/投资者教育语境，未给个人自我约束阈值。 | 未验证 | 关；无数值出处，不启用候选阻断 |
| 手动禁投到期。本人创建 `cooling_off` 或 `mute` restriction，`until` 到期后才可成为候选信号的可执行输入；删除时间不能改写过去的候选。 | 契约允许 `until`，`cooling_off` 必须带时区且严格晚于服务端当前时刻，`origin/main:docs/api-contract.md:1049-1064`；当前校验在 `origin/main:src/backend/app/api/v1/restrictions.py:224-232`。 | 未验证。未找到针对个人自我禁投期限的统一监管数字。 | 仓内定义 | 关；默认无禁投，用户显式创建后按 `until` 生效 |
| 止损后同证券冷却。止损事件发生后，同一用户、同一证券的后续候选在窗口内阻断，止损日不计为后续开市日。 | `cooling_off_after_stop.enabled=false`、`days=3`；`origin/main:config/risk_controls.yaml:40-42`；schema 为 `origin/main:src/backend/app/config_files.py:618-620`；旧审计记录 `origin/docs/T-R112@255253bf:docs/strategies/T-R112/params.md:73-74`、`origin/docs/T-R115@7e6e3a99:docs/strategies/T-R115/tracking_validation_plan.md:28-29`；主线未实现止损事件接线与冷却状态。 | 米筐回测说明止盈止损配置但没有止损后冷静期日数，https://www.ricequant.com/doc/quant/backtest.html；MoneySense 的暂停建议是一般教育做法，https://www.moneysense.gov.sg/investments/behavioural-science-and-investing/。 | 未验证 | 关；保留 `days=3` 作为仓内候选，不启用 |
| 同模板冷却。同一用户、同一证券、同一策略版本的候选，在上一次候选或执行事件后的窗口内不重复放行。 | `same_template_cooldown_days=3`；`origin/main:config/risk_controls.yaml:43`；schema 为 `origin/main:src/backend/app/config_files.py:623-627`；旧审计记录 `origin/docs/T-R112@255253bf:docs/strategies/T-R112/params.md:75`、`origin/docs/T-R115@7e6e3a99:docs/strategies/T-R115/tracking_validation_plan.md:30`；主线未实现起点、版本键和结束时点判定。 | 米筐回测说明未规定同模板冷却日数，https://www.ricequant.com/doc/quant/backtest.html。 | 未验证 | 关；不改代码现值，待完整事件链验证 |
| 亏损连败暂停。本人策略版本的模拟跟踪只取 `state=complete` 且 `direction_correct=false` 的连续结果，边沿达到后写系统暂停和 `paused_until`。 | `rc5_loss_streak_drawdown.enabled=true`、`strategy_sim_fail_streak=5`、`pause_on_trigger=true`、`pause_days=5`；`origin/main:config/risk_controls.yaml:23,26-28`；暂停链与 `paused_until` 为 `origin/main:src/backend/app/feedback/pause.py:291-358`、`origin/main:docs/api-contract.md:704-709`；旧审计记录 `origin/docs/T-R112@255253bf:docs/strategies/T-R112/params.md:77`、`origin/docs/T-R115@7e6e3a99:docs/strategies/T-R115/tracking_validation_plan.md:32`。 | Cambridge 连胜/连败风险偏好研究讨论运行序列对风险选择的机制，https://www.cambridge.org/core/journals/judgment-and-decision-making/article/not-all-streaks-are-the-same-individual-differences-in-risk-preferences-during-runs-of-gains-and-losses/C17AED8C1CAE94D7F79ACE14E2BD4900；未证明五次或五个交易日。 | 机制有据，数值未验证 | 维持现值（开），数值未验证，改默认须用户拍板 |

## 可见时点与禁用未来函数

- 评估时点记为 `at`。成交的执行时刻、计划的生效时刻、候选信号的 `created_at`、跟踪结果的 `exit_at` 以及每条记录的 `available_at` 都必须不晚于 `at`。冲突修订、缺证或覆盖不完整时返回缺口，不把缺口当作没有触发。
- 连续亏损只用已闭合段的本人成交、价格、费用和证据。自高点回撤只用本人净值点的 `at`、`available_at`。违反计划只用本人计划版本、计划生效/结束时点、本人成交执行时点和覆盖完整性。
- 频繁交易候选只统计本人 `trades`，按北京时间交易日计算笔数、成交额和换手。阈值冻结前不产生阻断。
- 手动限制的候选命中按 `[restriction.created_at, restriction.removed_at)` 与 `until` 的 PIT 口径。服务端当前时间只用于展示状态和创建时的未来校验，不能重写历史候选。
- 止损后冷却必须等待可追溯的本人止损事件及其可见时点。同证券同模板冷却必须同时看到证券、策略版本、候选或执行事件的可见时点。
- 亏损连败暂停只用本人策略版本的 `complete` 跟踪结果，按 `exit_at` 排序，`pending`、`unavailable`、`excluded` 和未来的 `exit_at` 均排除。暂停结束只由 `paused_until` 到期或用户按契约恢复。

## 当前边界

`/restrictions` 的创建、列表和删除入口在主线存在，但候选写入处仍只按目标和 `until` 与 `content.created_at` 比较，未完整落实契约要求的创建下界、删除上界和历史 PIT 重查。`cooling_off_after_stop` 与 `same_template_cooldown_days` 在主线只见配置和 schema，未见候选写入门控。RC5 的连续亏损、回撤和模拟失败评估及系统暂停函数存在，生产接线和完整用户样本不由本文推断。

计数：有据 0；机制有据数值未验证 3；仓内定义 2；未验证 3。
