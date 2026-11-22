# T-R112 主线四功能参数出处核查

- `lifecycle: draft`
- `G7: ☐`
- 角色：策略研究员。本卡只记录参数出处与缺证，输出保持“候选信号”措辞，不构成荐股或交易指令。
- 基准：`origin/main`。代码位置按本轮主线文件核对，仓内文档和团队报告只记作“仓内定义”。
- 判断类参数逐条联网核验。URL 后的状态码均为本轮 `curl -sS -L -o /dev/null -w '%{http_code}'` 实测值。相近文献或同类产品做法只证明方法存在，A 股有效性仍为“未验证（待复测）”；调参类均标“待回测”。

## 工程取值（不需研究出处）

以下是协议、调度、容量、缓存和实现保护参数。结论统一为“工程取值”，不计入未验证；当前值和代码位置照录，不改默认值。

| 参数 | 当前值 | 代码位置（origin/main） | 结论 | 建议 |
|---|---:|---|---|---|
| `realtime.schema_version` | 1 | `config/realtime.yaml:3` | 工程取值 | 保持版本值 |
| `intervals.quote_interval_s` | 15 秒 | `config/realtime.yaml:5` | 工程取值 | 维持现值，按延迟和配额监测 |
| `intervals.all_market_interval_s` | 60 秒 | `config/realtime.yaml:6` | 工程取值 | 维持现值，按覆盖和配额监测 |
| `intervals.pro_tier1_interval_s` | 60 秒 | `config/realtime.yaml:7` | 工程取值 | 维持现值，按负载监测 |
| `intervals.pro_tier2_interval_s` | 300 秒 | `config/realtime.yaml:8` | 工程取值 | 维持现值，按负载监测 |
| `intervals.stale_threshold_s` | `null` | `config/realtime.yaml:9` | 工程取值 | 保持默认 `null` |
| `effective_stale_threshold_s` | 30 秒（`2×15`） | `src/backend/app/config_files.py:63-68` | 工程取值 | 保持计算关系，监测延迟分位数 |
| `universe.tier1_cap` | 1500 | `config/realtime.yaml:17` | 工程取值 | 保持容量上限 |
| `universe.universe_hard_cap` | 4000 | `config/realtime.yaml:18` | 工程取值 | 保持容量上限 |
| `universe.tier1_alert_ratio` | 0.8 | `config/realtime.yaml:19` | 工程取值 | 保持告警比例，按负载监测 |
| `universe.tier1_priority` | holding→focus→multi_user_watch→single_user_watch | `config/realtime.yaml:20` | 工程取值 | 保持调度优先级 |
| `watchlist.per_user_cap` | 100 | `config/realtime.yaml:22` | 工程取值 | 保持容量上限 |
| `watchlist.focus_cap` | 20 | `config/realtime.yaml:23` | 工程取值 | 保持容量上限 |
| `watchlist.holdings_import_warn` | 200 | `config/realtime.yaml:24` | 工程取值 | 保持提示阈值，按负载监测 |
| `flip_detection.debounce_rounds` | 2 轮 | `config/realtime.yaml:26` | 工程取值 | 保持去抖轮数，变更须回归验证 |
| `adaptive.enabled` | `true` | `config/realtime.yaml:29` | 工程取值 | 保持开关 |
| `adaptive.unchanged_ratio` | 0.8 | `config/realtime.yaml:30` | 工程取值 | 保持比例，变更须回归验证 |
| `adaptive.unchanged_rounds` | 5 轮 | `config/realtime.yaml:31` | 工程取值 | 保持轮数，变更须回归验证 |
| `adaptive.breaker_cooldown_s` | 300 秒 | `config/realtime.yaml:32` | 工程取值 | 保持熔断冷却，变更须回归验证 |
| `notify.cadence_default` | `1min` | `config/realtime.yaml:34` | 工程取值 | 保持默认节奏 |
| `notify.sse_heartbeat_s` | 15 秒 | `config/realtime.yaml:35`；硬编码 `src/backend/app/api/v1/notifications.py:215,226` | 工程取值 | 保持心跳常量 |
| `notify.sse_replay_window_s` | 600 秒 | `config/realtime.yaml:36`；硬编码 `src/backend/app/notify/transport.py:54-55,73-76,146` | 工程取值 | 保持重放窗口 |
| `notify.poll_fallback_s` | 15 秒 | `config/realtime.yaml:37`；契约 `docs/api-contract.md:932`、`1475` | 工程取值 | 保持轮询间隔 |
| `degraded_profile.quote_interval_s` | 60 秒 | `config/realtime.yaml:40` | 工程取值 | 保持降级轮询间隔 |
| `ingest.heartbeat.interval_s` | 15 秒 | `config/ingest.yaml:26`；`src/backend/app/workers/ingest.py:232-233` | 工程取值 | 保持心跳间隔 |
| `ingest.heartbeat.stale_after_s` | 120 秒 | `config/ingest.yaml:28`；`src/backend/app/api/v1/health.py:118-152` | 工程取值 | 保持过期判定 |
| SSE 自动重试字面量 | 3000 毫秒 | `src/backend/app/api/v1/notifications.py:197` | 工程取值 | 保持毫秒常量 |
| SSE 循环睡眠 | 1 秒 | `src/backend/app/api/v1/notifications.py:231` | 工程取值 | 保持循环常量 |
| 测试订阅轮询 timeout | 0.01 秒 | `src/backend/app/intraday/consumer.py:38` | 工程取值 | 仅保持测试专用值 |
| `signal-rt` worker tick | 1 秒 | `src/backend/app/workers/signal_rt.py:31` | 工程取值 | 保持 tick 常量 |
| `aggregates.t_view` 过期倍数 | `2×interval_s` | `src/backend/app/aggregates/t_view.py:247` | 工程取值 | 保持缓存过期关系 |

## 判断类参数（逐条联网核验）

| 参数 | 当前值 | 代码位置（origin/main） | 公开出处或同类产品做法（URL + 状态） | 结论 | 建议 |
|---|---:|---|---|---|---|
| `boards.main` | `true` | `config/realtime.yaml:10-11` | [上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)（200）涵盖沪市股票交易范围 | 数值有据（制度范围；具体扫描开关仍待复测）；A 股有效性未验证（待复测） | 不改值，待复测 |
| `boards.chinext` | `true` | `config/realtime.yaml:12` | [深交所创业板交易规则](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)（200）确认创业板制度范围 | 数值有据（制度范围；具体扫描开关仍待复测）；A 股有效性未验证（待复测） | 不改值，待复测 |
| `boards.star` | `true` | `config/realtime.yaml:13` | [上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)（200）涵盖科创板适用证券 | 数值有据（制度范围；具体扫描开关仍待复测）；A 股有效性未验证（待复测） | 不改值，待复测 |
| `boards.bse` | `false` | `config/realtime.yaml:14` | [北交所规则发布页](https://www.bse.cn/jygl_list/200028217.html)（403）无法核验 V1 排除策略 | 未验证 | 保持拦截，不建议启用 |
| `boards.etf_cb_holdings_only` | `true` | `config/realtime.yaml:15` | [华泰行情软件手册](https://download.htsc.com.cn/download/doc/HTSC_GJB_MANUAL_V8_40.pdf)（200）展示自选股、持仓股及 ETF 等品种 | 机制有据，数值未验证（同类产品做法；具体筛选开关待复测）；A 股有效性未验证（待复测） | 不改值，待复测 |
| `flip_detection.invalidation_immediate` | `true` | `config/realtime.yaml:27` | [米筐回测风控说明](https://www.ricequant.com/doc/quant/backtest.html)（200）说明止盈止损及大盘择时阶段，但未规定即时失效确认 | 未验证 | 保持现值，不建议启用新语义 |
| `degraded_profile.holdings_only` | `true` | `config/realtime.yaml:39` | [华泰软件说明](https://www.htsc.com.cn/browser/mz/index.jsp)（200）说明行情、账户和持仓服务并行提供 | 机制有据，数值未验证（同类产品做法；本项目降级开关待复测）；A 股有效性未验证（待复测） | 不改值，待复测 |
| `degraded_profile.tier2_enabled` | `false` | `config/realtime.yaml:41` | [涨乐财富通官方页面](https://www.htsc.com.cn/browser/mobile/mobileSecurities/SoftwareDownload.jsp?currentMenu=SoftwareDownload)（200）介绍分层功能但未给出本项目 Tier-2 开关 | 未验证 | 保持关闭，不建议启用 |
| 市场概览 `breadth` | `null` | `src/backend/app/aggregates/service.py:62-73` | [市场宽度研究](https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf)（200）讨论宽度指标，未定义本系统 `null` 输出 | 未验证 | 保持 `null`，不建议启用结论 |
| 宽度上行阈值候选 | `width_ma > 0.50` | 主线未实现；`src/backend/app/aggregates/service.py:67-69` 保持 `regime=null` | [市场宽度研究](https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf)（200）采用宽度概念但未给出 0.50 | 未验证 | 不改值，不建议启用，待回测 |
| 宽度下行阈值候选 | `width_ma < 0.40` | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | [市场宽度研究](https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf)（200）采用宽度概念但未给出 0.40 | 未验证 | 不改值，不建议启用，待回测 |
| 宽度短窗口候选 | 20 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | [20 日均线研究](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6858299)（403）检验 20 日均线；[米筐技术分析](https://www.ricequant.com/doc/quant/technical-analysis)（200）支持周期参数 | 机制有据，数值未验证（文献采用/同类平台做法；非本项目阈值）；A 股有效性未验证（待复测）；调参待回测 | 不建议直接启用，待回测 |
| 宽度长窗口候选 | 60 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | [市场均线策略研究](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5430117)（403）比较短长均线；[米筐技术分析](https://www.ricequant.com/doc/quant/technical-analysis)（200）支持周期参数 | 机制有据，数值未验证（文献采用/同类平台做法；未规定 60）；A 股有效性未验证（待复测）；调参待回测 | 不建议直接启用，待回测 |
| regime 指数 | `000300.SH` | `src/backend/app/tracking/models.py:24`、`src/backend/app/tracking/service.py:300` | [中证沪深300编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf)（200）确认指数身份 | 数值有据（指数身份）；A 股有效性未验证（待复测） | 仅作候选信号，待复测 |
| regime 短均线 | 20 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:68` | [市场均线策略研究](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6858299)（403）采用 20 日均线；[状态分段研究](https://arxiv.org/abs/2208.11574)（200）讨论状态分段 | 机制有据，数值未验证（文献采用相近方法；未规定本项目窗口）；A 股有效性未验证（待复测）；调参待回测 | 不建议直接启用，待回测 |
| regime 长均线 | 60 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:68` | [状态分段研究](https://arxiv.org/abs/2208.11574)（200）讨论状态分段；[米筐技术分析](https://www.ricequant.com/doc/quant/technical-analysis)（200）支持周期参数 | 机制有据，数值未验证（文献采用/同类平台做法；未规定 60）；A 股有效性未验证（待复测）；调参待回测 | 不建议直接启用，待回测 |
| regime 最少指数值 | 45 根 | 主线未实现；`src/backend/app/aggregates/service.py:68` | [MIT 统计教材](https://web.mit.edu/14.380/www/readings/reading0.pdf)（200）记载 n≥30 的正态近似经验法则 | 机制有据，数值未验证（统计惯例；未证明本项目 45 门槛）；A 股有效性未验证（待复测）；调参待回测 | 不建议直接启用，待回测 |
| regime 最少宽度值 | 15 个 | 主线未实现；`src/backend/app/aggregates/service.py:68` | [OpenStax 中心极限定理教材](https://openstax.org/books/statistics/pages/7-1-the-central-limit-theorem-for-sample-means-averages)（200）说明大样本近似，未给出 15 门槛 | 未验证 | 不建议启用，待回测 |
| regime 防抖天数 | 2 | `config/risk_controls.yaml:17`；`src/backend/app/risk/settings.py:27-28` | [状态分段研究](https://arxiv.org/abs/2208.11574)（200）未规定 2 日确认 | 未验证 | 不建议启用，待回测 |
| `regime_ranges.uptrend` | `[60,90]`% | `config/risk_controls.yaml:13-15`；`src/backend/app/risk/settings.py:26-29` | [米筐回测风控说明](https://www.ricequant.com/doc/quant/backtest.html)（200）提供大盘择时和止盈止损配置 | 机制有据，数值未验证（同类量化平台风控做法；未规定该区间）；A 股有效性未验证（待复测）；调参待回测 | 不改值，待回测 |
| `regime_ranges.range` | `[40,60]`% | `config/risk_controls.yaml:15`；`src/backend/app/risk/settings.py:27` | [聚宽 API 手册](https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf)（200）记录组合仓位字段和仓位管理接口 | 机制有据，数值未验证（同类量化平台做法；未规定该区间）；A 股有效性未验证（待复测）；调参待回测 | 不改值，待回测 |
| `regime_ranges.downtrend` | `[0,30]`% | `config/risk_controls.yaml:16`；`src/backend/app/risk/settings.py:27` | [米筐策略 API](https://www.ricequant.com/doc/quant/strategy-api.html)（200）支持目标仓位比例下单 | 机制有据，数值未验证（同类量化平台做法；未规定该区间）；A 股有效性未验证（待复测）；调参待回测 | 不改值，待回测 |
| `cooling_off_after_stop.enabled` | `false` | `config/risk_controls.yaml:40-42` | [米筐回测风控说明](https://www.ricequant.com/doc/quant/backtest.html)（200）说明止盈止损风控，但未规定止损后冷静期开关 | 未验证 | 保持关闭，不建议启用 |
| `cooling_off_after_stop.days` | 3 个交易日 | `config/risk_controls.yaml:42`；`src/backend/app/config_files.py:618-620` | [深交所新股交易机制说明](https://www.szse.cn/www/investor/knowledge/t20230509_600303.html)（200）给出上市初期 5 个交易日制度窗口，与止损冷静期无直接对应 | 未验证 | 不改值，不建议启用，待回测 |
| `same_template_cooldown_days` | 3 个交易日 | `config/risk_controls.yaml:43`；`src/backend/app/config_files.py:623-627` | [米筐回测风控说明](https://www.ricequant.com/doc/quant/backtest.html)（200）未规定同模板冷却日数 | 未验证 | 不改值，不建议启用 |
| `new_listing_min_days` | 30 个交易日 | `config/risk_controls.yaml:39`；`src/backend/app/config_files.py:623-627` | [深交所新股交易机制说明](https://www.szse.cn/www/investor/knowledge/t20230509_600303.html)（200）采用上市前五个交易日特殊机制 | 机制有据，数值未验证（制度存在上市初期窗口；未规定 30）；A 股有效性未验证（待复测）；调参待回测 | 不改值，待回测 |
| `rc5_loss_streak_drawdown.pause_days` | 5 个交易日 | `config/risk_controls.yaml:28`；`src/backend/app/config_files.py:573-579` | [米筐回测风控说明](https://www.ricequant.com/doc/quant/backtest.html)（200）支持策略最大亏损等风控，但未规定连续亏损暂停 5 日 | 未验证 | 不改值，不建议启用 |
| 复盘统计 `n` | 0 | `src/backend/app/strategy/promotions.py:220`；`src/backend/app/strategy/reviews.py:178` | [MIT 统计教材](https://web.mit.edu/14.380/www/readings/reading0.pdf)（200）说明近似法则依赖足够样本，不能把 0 当可判定样本 | 机制有据，数值未验证（统计惯例支持不可判定）；A 股有效性未验证（待复测） | 保持 `null`/`small_sample`，不产生结论 |
| 复盘 `small_sample` 阈值 | `n<30` | `src/backend/app/tracking/service.py:195,515`；`config/strategies/hold_risk_monitor.yaml:149` | [MIT 统计教材](https://web.mit.edu/14.380/www/readings/reading0.pdf)（200）记载 n≥30 的中心极限定理经验法则，并强调取决于分布 | 数值有据（统计惯例；30 是经验法则而非本项目定理）；A 股有效性未验证（待复测）；调参待回测 | 保持小样本标记，不放宽断言 |
| 复盘可显示下限 | `n>=5`，否则 value 为 `null` | `src/backend/app/tracking/service.py:186-195,507-515` | [OpenStax 中心极限定理教材](https://openstax.org/books/statistics/pages/7-1-the-central-limit-theorem-for-sample-means-averages)（200）未给出 5 的统一显示下限 | 未验证 | 保持 `null`，不建议启用结论 |
| 复盘窗口 | `120 trading days` | `src/backend/app/strategy/promotions.py:220`；`src/backend/app/strategy/reviews.py:178` | [米筐回测说明](https://www.ricequant.com/doc/quant/backtest.html)（200）提供可配置回测区间；[米筐策略 API](https://www.ricequant.com/doc/quant/strategy-api.html)（200）提供历史窗口参数 | 机制有据，数值未验证（同类量化平台做法；未规定 120）；A 股有效性未验证（待复测）；调参待回测 | 不改值，待窗口敏感性回测 |
| `outcome_metrics` 缺证状态 | 当前未生成可判定值，数据库字段可空 | `src/backend/app/db/tables/reviews.py:91`；日报投影 `src/backend/app/reports/service.py:363` | [聚宽 API 手册](https://cdn.joinquant.com/help/img/JoinQuantAPI.pdf)（200）说明回测数据和结果接口，但未定义本项目结果指标口径 | 未验证 | 保持 `null`，无出处不建议启用 |

## 本轮结论

- 参数行共 63 行：工程取值 31 项、数值有据 5 项、机制有据数值未验证 13 项、无出处未验证 14 项。工程取值不计入未验证；机制有据数值未验证与无出处项计入未验证合计 27 项。数值有据项仍按项目语境复测，调参项标“待回测”。
- 新增出处清单：上交所交易规则、深交所交易规则、北交所规则发布页、华泰行情软件手册与涨乐财富通页面、市场宽度研究、20 日均线研究、市场均线策略研究、状态分段研究、中证沪深300编制方案、MIT 统计教材、OpenStax 统计教材、米筐技术分析/回测/策略 API、聚宽 API 手册。
- 市场概览主线继续返回 `null`，宽度阈值、窗口与 regime 候选仍是仓内定义，不能写成已实现或已验收。无出处的判断类参数不建议启用，不改任何默认值。
- 保持 `lifecycle=draft`、`G7=☐`、“候选信号”措辞，不荐股，不引入未来函数。
