# T-R114 未验证参数补证追踪

- lifecycle: draft
- G7: ☐
- 本文是对 `origin/docs/T-R112:docs/strategies/T-R112/params.md` 的补证追踪，不复制原文。只处理其中结论为“未验证”或“机制有据，数值未验证”的 27 行，默认值不变。
- URL 状态码均为本轮 `curl -sS -L -A 'Mozilla/5.0' -o /dev/null -w '%{http_code}'` 实测。北交所页面先以同一 UA 建立会话后返回 200；SSRN 返回 403，不作为数值证据。

| 参数 | 当前值 | 代码位置（沿用 params.md） | T-R112 结论 | 本轮出处（URL+条款/页+状态码） | 本轮结论 | 建议 |
|---|---:|---|---|---|---|---|
| `boards.bse` | `false` | `config/realtime.yaml:14` | 未验证 | https://www.bse.cn/jygl_list/200028217.html，《北京证券交易所交易规则》§1.2、§10.6（200） | 未验证。规则证明制度存在，不证明本产品应纳入扫描 | 保持拦截，北交所只作候选信号，不建议启用 |
| `boards.etf_cb_holdings_only` | `true` | `config/realtime.yaml:15` | 机制有据，数值未验证 | https://download.htsc.com.cn/download/doc/HTSC_GJB_MANUAL_V8_40.pdf，§2.1“持仓股”、§2.13“ETF基金”（200） | 机制有据，数值未验证。手册展示持仓和 ETF 分类，未给出本开关 | 保持值，待筛选口径复测 |
| `flip_detection.invalidation_immediate` | `true` | `config/realtime.yaml:27` | 未验证 | https://www.ricequant.com/doc/quant/backtest.html，风控与大盘择时说明（200）；关键词“即时失效/去抖/反转确认”未找到同值条款 | 未验证 | 保持值，不把候选信号升级为即时交易语义 |
| `degraded_profile.holdings_only` | `true` | `config/realtime.yaml:39` | 机制有据，数值未验证 | https://www.htsc.com.cn/browser/mz/index.jsp，行情、账户、持仓服务说明（200） | 机制有据，数值未验证。产品页面未规定降级时只保留持仓 | 保持值，降级结果仅作候选信号 |
| `degraded_profile.tier2_enabled` | `false` | `config/realtime.yaml:41` | 未验证 | https://www.htsc.com.cn/browser/mobile/mobileSecurities/SoftwareDownload.jsp?currentMenu=SoftwareDownload，分层产品介绍（200）；关键词“Tier-2/降级二级扫描”未找到数值 | 未验证 | 保持关闭，不建议启用 |
| 市场概览 `breadth` | `null` | `src/backend/app/aggregates/service.py:62-73` | 未验证 | https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf，pp.1-2，advance/decline 公式（200） | 工程取值。`null` 是缺数据保护哨兵，不是研究参数；文献未规定本输出 | 保持 `null`，候选信号须先有数据 |
| 宽度上行阈值候选 | `width_ma > 0.50` | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | 未验证 | https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf，pp.1-3 定义 breadth（200）；关键词“0.50/50% 上行阈值”未给出项目同值 | 未验证 | 不改值，不建议启用，待 A 股回测 |
| 宽度下行阈值候选 | `width_ma < 0.40` | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | 未验证 | https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf，pp.1-3 无 0.40 阈值（200）；StockCharts breadth 说明 https://articles.stockcharts.com/article/articles-dancing-2015-08-advance-decline-misc-indicators-chapter-6-cgmbi/（200）也未规定本值 | 未验证 | 不改值，不建议启用，待 A 股回测 |
| 宽度短窗口候选 | 20 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | 机制有据，数值未验证 | https://rqopen.ricequant.com/doc/quant/technical-analysis.html，`reg_indicator` 示例 `win_size=20`（200）；SSRN 6858299（403）不计数值证据 | 机制有据，数值未验证。平台支持 20 窗口，但未规定 breadth 20 日 | 仅作候选信号，待窗口敏感性回测 |
| 宽度长窗口候选 | 60 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | 机制有据，数值未验证 | https://www.ricequant.com/doc/rqdata/cli/manual，VOLT20/VOLT60、WMA20/WMA60 条目（200）；未规定 breadth 60 日 | 机制有据，数值未验证 | 仅作候选信号，待窗口敏感性回测 |
| regime 短均线 | 20 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:68` | 机制有据，数值未验证 | https://rqopen.ricequant.com/doc/quant/technical-analysis.html，MA 与 `win_size=20` 示例（200）；https://arxiv.org/abs/2208.11574，状态分段方法（200）未给本项目窗口 | 机制有据，数值未验证 | 不建议直接启用，待回测 |
| regime 长均线 | 60 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:68` | 机制有据，数值未验证 | https://www.ricequant.com/doc/rqdata/cli/manual，WMA60/VOLT60（200）；https://arxiv.org/abs/2208.11574，状态分段（200）未给 60 | 机制有据，数值未验证 | 不建议直接启用，待回测 |
| regime 最少指数值 | 45 根 | 主线未实现；`src/backend/app/aggregates/service.py:68` | 机制有据，数值未验证 | https://web.mit.edu/14.380/www/readings/reading0.pdf，样本量经验法则 n≥30（200）；未给 45 根门槛 | 机制有据，数值未验证 | 不建议直接启用，待回测 |
| regime 最少宽度值 | 15 个 | 主线未实现；`src/backend/app/aggregates/service.py:68` | 未验证 | https://openstax.org/books/statistics/pages/7-1-the-central-limit-theorem-for-sample-means-averages，CLT 大样本说明（200）；关键词“breadth minimum 15”未找到 | 未验证 | 不建议启用，待回测 |
| regime 防抖天数 | 2 | `config/risk_controls.yaml:17`；`src/backend/app/risk/settings.py:27-28` | 未验证 | https://arxiv.org/abs/2208.11574，状态分段（200）；关键词“two-day confirmation/debounce”未规定 2 日 | 未验证 | 不建议启用，待回测 |
| `regime_ranges.uptrend` | `[60,90]%` | `config/risk_controls.yaml:13-15`；`src/backend/app/risk/settings.py:26-29` | 机制有据，数值未验证 | https://www.ricequant.com/doc/quant/backtest.html，大盘择时和风控可配置（200）；未规定 60–90% | 机制有据，数值未验证 | 保持值，候选信号待回测 |
| `regime_ranges.range` | `[40,60]%` | `config/risk_controls.yaml:15`；`src/backend/app/risk/settings.py:27` | 机制有据，数值未验证 | https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf，组合与仓位字段（200）；未规定 40–60% | 机制有据，数值未验证 | 保持值，候选信号待回测 |
| `regime_ranges.downtrend` | `[0,30]%` | `config/risk_controls.yaml:16`；`src/backend/app/risk/settings.py:27` | 机制有据，数值未验证 | https://www.ricequant.com/doc/quant/strategy-api.html，目标仓位比例接口（200）；未规定 0–30% | 机制有据，数值未验证 | 保持值，候选信号待回测 |
| `cooling_off_after_stop.enabled` | `false` | `config/risk_controls.yaml:40-42` | 未验证 | https://www.ricequant.com/doc/quant/backtest.html，止盈止损功能说明（200）；关键词“stop cooldown enabled”未给开关 | 未验证 | 保持关闭，不建议启用 |
| `cooling_off_after_stop.days` | 3 个交易日 | `config/risk_controls.yaml:42`；`src/backend/app/config_files.py:618-620` | 未验证 | https://www.szse.cn/www/investor/knowledge/t20230509_600303.html，上市初期 5 个交易日制度（200）；与止损冷静期无直接对应 | 未验证 | 保持值，不建议启用 |
| `same_template_cooldown_days` | 3 个交易日 | `config/risk_controls.yaml:43`；`src/backend/app/config_files.py:623-627` | 未验证 | https://www.ricequant.com/doc/quant/backtest.html，策略回测风控（200）；关键词“same template cooldown”未找到数值 | 未验证 | 保持值，不建议启用 |
| `new_listing_min_days` | 30 个交易日 | `config/risk_controls.yaml:39`；`src/backend/app/config_files.py:623-627` | 机制有据，数值未验证 | https://www.szse.cn/www/investor/knowledge/t20230509_600303.html，上市前 5 个交易日特殊机制（200） | 机制有据，数值未验证。制度窗口存在，但不是 30 日 | 保持值，待上市样本回测 |
| `rc5_loss_streak_drawdown.pause_days` | 5 个交易日 | `config/risk_controls.yaml:28`；`src/backend/app/config_files.py:573-579` | 未验证 | https://www.ricequant.com/doc/quant/backtest.html，最大亏损等风控（200）；关键词“loss streak pause 5 days”未找到 | 未验证 | 保持值，不建议启用 |
| 复盘统计 `n` | 0 | `src/backend/app/strategy/promotions.py:220`；`src/backend/app/strategy/reviews.py:178` | 机制有据，数值未验证 | https://web.mit.edu/14.380/www/readings/reading0.pdf，近似需足够样本（200）；未规定用 0 表示缺证 | 机制有据，数值未验证 | 保持 `null`/`small_sample`，不产生结论 |
| 复盘可显示下限 | `n>=5`，否则 value 为 `null` | `src/backend/app/tracking/service.py:186-195,507-515` | 未验证 | https://openstax.org/books/statistics/pages/7-1-the-central-limit-theorem-for-sample-means-averages，样本量至少 30 的近似说明（200）；未给显示下限 5 | 未验证 | 保持 `null`，不建议启用结论 |
| 复盘窗口 | `120 trading days` | `src/backend/app/strategy/promotions.py:220`；`src/backend/app/strategy/reviews.py:178` | 机制有据，数值未验证 | https://rqalipay.ricequant.com/doc/quant/backtest，回测区间可配置（200）；https://www.ricequant.com/doc/quant/strategy-api.html，历史窗口参数（200）；未规定 120 日 | 机制有据，数值未验证 | 保持值，做窗口敏感性回测 |
| `outcome_metrics` 缺证状态 | 当前未生成可判定值，数据库字段可空 | `src/backend/app/db/tables/reviews.py:91`；日报投影 `src/backend/app/reports/service.py:363` | 未验证 | https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf，回测结果接口（200）；未定义本项目缺证字段 | 工程取值。可空和 `null` 是缺证保护，不是可调研究参数 | 保持可空，不产生候选结论 |

计数：本轮升为数值有据 0；仍机制有据 13；仍未验证 12；改判工程取值 2。
