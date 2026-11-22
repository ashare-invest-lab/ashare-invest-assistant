# T-R112 主线四功能参数出处核查

- `lifecycle: draft`
- `G7: ☐`
- 角色：策略研究员。本卡只记录参数出处与缺证，输出保持“候选信号”措辞，不构成荐股或交易指令。
- 基准：`origin/main`。代码位置的行号按本轮 `git show origin/main:<path> | nl -ba` 实测。仓内文档和团队报告只记作“仓内定义”。
- 本轮 URL 状态均以 `curl -sS -L -o /dev/null -w '%{http_code}'` 实测。SSE 资料只证明协议机制，不能证明本项目数值。论文只证明文献采用相近方法，A 股有效性仍为“未验证（待复测）”。调参阈值均“待回测”。

| 参数 | 当前值 | 代码位置（origin/main） | 公开出处或同类产品做法（URL + 状态） | 结论 | 建议 |
|---|---:|---|---|---|---|
| `realtime.schema_version` | 1 | `config/realtime.yaml:3` | [Pydantic 配置模型](https://docs.pydantic.dev/latest/concepts/models/)（200）；版本号为仓内格式 | 未验证 | 建议复核/补出处，不改值 |
| `intervals.quote_interval_s` | 15 秒 | `config/realtime.yaml:5` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）说明流式订阅，不给 15 秒轮询标准 | 未验证 | 建议回测延迟、配额后补出处，不启用新值 |
| `intervals.all_market_interval_s` | 60 秒 | `config/realtime.yaml:6` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）；无全市场 60 秒要求 | 未验证 | 建议回测覆盖和配额，补出处 |
| `intervals.pro_tier1_interval_s` | 60 秒 | `config/realtime.yaml:7` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）；无本项目 Tier-1 数值 | 未验证 | 建议回测后补出处 |
| `intervals.pro_tier2_interval_s` | 300 秒 | `config/realtime.yaml:8` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）；无本项目 Tier-2 数值 | 未验证 | 建议回测后补出处 |
| `intervals.stale_threshold_s` | `null` | `config/realtime.yaml:9` | [RFC 6202](https://www.rfc-editor.org/rfc/rfc6202)（200）讨论流式连接，不规定行情陈旧秒数 | 未验证 | 建议复核/补出处，不改默认 `null` |
| `effective_stale_threshold_s` | 30 秒（`2×15`） | `src/backend/app/config_files.py:63-68` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）；无 2×轮询依据 | 未验证 | 建议用同源延迟分位数回测，补出处 |
| `boards.main` | `true` | `config/realtime.yaml:10-11` | [上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)（200）支持沪市规则范围，不支持本产品扫描开关 | 未验证 | 建议复核范围出处 |
| `boards.chinext` | `true` | `config/realtime.yaml:12` | [深交所交易规则](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)（200）支持创业板制度，不支持扫描开关 | 未验证 | 建议复核范围出处 |
| `boards.star` | `true` | `config/realtime.yaml:13` | [上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)（200）支持科创板制度，不支持扫描开关 | 未验证 | 建议复核范围出处 |
| `boards.bse` | `false` | `config/realtime.yaml:14` | [北交所交易规则发布页](https://www.bse.cn/jygl_list/200028217.html)（403）；可访问的规则资料不能证明本产品 V1 排除策略 | 未验证 | 建议保持拦截，补出处，不改默认值 |
| `boards.etf_cb_holdings_only` | `true` | `config/realtime.yaml:15` | [上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)（200）不支持本产品展示模式 | 未验证 | 建议复核/补出处 |
| `universe.tier1_cap` | 1500 | `config/realtime.yaml:17` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）无本项目容量值 | 未验证 | 建议按配额和延迟回测，补出处 |
| `universe.universe_hard_cap` | 4000 | `config/realtime.yaml:18` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）无本项目池上限 | 未验证 | 建议回测后补出处 |
| `universe.tier1_alert_ratio` | 0.8 | `config/realtime.yaml:19` | [NIST 样本量说明](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm)（200）不支持容量告警比例 | 未验证 | 建议回测后补出处 |
| `universe.tier1_priority` | holding→focus→multi_user_watch→single_user_watch | `config/realtime.yaml:20` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）不规定用户池优先级 | 未验证 | 建议复核/补出处 |
| `watchlist.per_user_cap` | 100 | `config/realtime.yaml:22` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）不规定自选上限 | 未验证 | 建议回测负载并补出处 |
| `watchlist.focus_cap` | 20 | `config/realtime.yaml:23` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）不规定重点关注上限 | 未验证 | 建议回测负载并补出处 |
| `watchlist.holdings_import_warn` | 200 | `config/realtime.yaml:24` | [FINRA 日内交易说明](https://www.finra.org/investors/investing/investment-products/stocks/day-trading)（200）仅为风险教育，不支持导入提示值 | 未验证 | 建议复核/补出处 |
| `flip_detection.debounce_rounds` | 2 轮 | `config/realtime.yaml:26` | [RFC 6202](https://www.rfc-editor.org/rfc/rfc6202)（200）不规定信号去抖轮数 | 未验证 | 建议回测后补出处 |
| `flip_detection.invalidation_immediate` | `true` | `config/realtime.yaml:27` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）不规定失效确认策略 | 未验证 | 建议复核/补出处 |
| `adaptive.enabled` | `true` | `config/realtime.yaml:29` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）未规定自适应开关 | 未验证 | 建议复核/补出处 |
| `adaptive.unchanged_ratio` | 0.8 | `config/realtime.yaml:30` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）无更新时间不变比例标准 | 未验证 | 建议回测后补出处 |
| `adaptive.unchanged_rounds` | 5 轮 | `config/realtime.yaml:31` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）无连续轮数标准 | 未验证 | 建议回测后补出处 |
| `adaptive.breaker_cooldown_s` | 300 秒 | `config/realtime.yaml:32` | [RFC 6202](https://www.rfc-editor.org/rfc/rfc6202)（200）不规定 429/503 熔断时长 | 未验证 | 建议回测后补出处 |
| `notify.cadence_default` | `1min` | `config/realtime.yaml:34` | [WHATWG SSE](https://html.spec.whatwg.org/multipage/server-sent-events.html)（200）规定事件流，不规定通知合并节奏 | 未验证 | 建议复核/补出处 |
| `notify.sse_heartbeat_s` | 15 秒 | `config/realtime.yaml:35`；硬编码 `src/backend/app/api/v1/notifications.py:215,226` | [WHATWG SSE](https://html.spec.whatwg.org/multipage/server-sent-events.html)（200）允许注释保活，不规定 15 秒 | 未验证 | 建议回测连接保活后补出处 |
| `notify.sse_replay_window_s` | 600 秒 | `config/realtime.yaml:36`；硬编码 `src/backend/app/notify/transport.py:54-55,73-76,146` | [RFC 6202](https://www.rfc-editor.org/rfc/rfc6202)（200）不规定 10 分钟保留窗 | 未验证 | 建议回测重连率后补出处 |
| `notify.poll_fallback_s` | 15 秒 | `config/realtime.yaml:37`；契约 `docs/api-contract.md:932`、`1475` | [MDN SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)（200）未规定断线轮询数值 | 未验证 | 建议回测后补出处，不改默认值 |
| `degraded_profile.holdings_only` | `true` | `config/realtime.yaml:39` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）不规定证书降级展示 | 未验证 | 建议复核/补出处 |
| `degraded_profile.quote_interval_s` | 60 秒 | `config/realtime.yaml:40` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）无降级间隔标准 | 未验证 | 建议回测后补出处 |
| `degraded_profile.tier2_enabled` | `false` | `config/realtime.yaml:41` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）不规定 Tier-2 降级开关 | 未验证 | 建议保持关闭，补出处 |
| `ingest.heartbeat.interval_s` | 15 秒 | `config/ingest.yaml:26`；`src/backend/app/workers/ingest.py:232-233` | [WHATWG SSE](https://html.spec.whatwg.org/multipage/server-sent-events.html)（200）与采集心跳无数值对应 | 未验证 | 建议复核/补出处 |
| `ingest.heartbeat.stale_after_s` | 120 秒 | `config/ingest.yaml:28`；`src/backend/app/api/v1/health.py:118-152` | [RFC 6202](https://www.rfc-editor.org/rfc/rfc6202)（200）不规定采集心跳过期秒数 | 未验证 | 建议回测后补出处 |
| SSE 自动重试字面量 | 3000 毫秒 | `src/backend/app/api/v1/notifications.py:197` | [WHATWG SSE](https://html.spec.whatwg.org/multipage/server-sent-events.html)（200）定义 `retry` 字段但不规定 3000 | 未验证 | 建议回测后补出处 |
| SSE 循环睡眠 | 1 秒 | `src/backend/app/api/v1/notifications.py:231` | [MDN SSE](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)（200）不规定服务端循环周期 | 未验证 | 建议复核/补出处 |
| 测试订阅轮询 timeout | 0.01 秒 | `src/backend/app/intraday/consumer.py:38` | [Redis Pub/Sub 文档](https://redis.io/docs/latest/develop/interact/pubsub/)（200）不规定本测试轮询 timeout | 未验证 | 建议保持测试专用并补出处 |
| `signal-rt` worker tick | 1 秒 | `src/backend/app/workers/signal_rt.py:31` | [Alpaca 实时行情文档](https://docs.alpaca.markets/docs/real-time-stock-pricing-data)（200）不规定本地 tick 周期 | 未验证 | 建议回测后补出处 |
| `aggregates.t_view` 过期倍数 | `2×interval_s` | `src/backend/app/aggregates/t_view.py:247` | [RFC 6202](https://www.rfc-editor.org/rfc/rfc6202)（200）不规定行情快照过期倍数 | 未验证 | 建议复核/补出处 |
| 市场概览 `breadth` | `null` | `src/backend/app/aggregates/service.py:62-73` | [上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)（200）仅提供交易规则，不提供本系统宽度公式 | 未验证 | 建议保持 `null`，补来源后再评估 |
| 宽度上行阈值候选 | `width_ma > 0.50` | 主线未实现；`src/backend/app/aggregates/service.py:67-69` 保持 `regime=null` | [市场宽度论文](https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf)（200）只证明采用宽度，不证明 0.50 | 未验证 | 建议待回测，不建议启用 |
| 宽度下行阈值候选 | `width_ma < 0.40` | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | [市场宽度论文](https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf)（200）只证明采用宽度，不证明 0.40 | 未验证 | 建议待回测，不建议启用 |
| 宽度短窗口候选 | 20 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | [市场宽度论文](https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf)（200）不规定本窗口 | 未验证 | 建议待回测，不建议启用 |
| 宽度长窗口候选 | 60 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:67-69` | [市场宽度论文](https://www.pure.ed.ac.uk/ws/portalfiles/portal/16837254/Jacobsen_SSRN_id2449344.pdf)（200）不规定本窗口 | 未验证 | 建议待回测，不建议启用 |
| regime 指数 | `000300.SH` | `src/backend/app/tracking/models.py:24`、`src/backend/app/tracking/service.py:300` | [中证沪深300编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf)（200）直接支持指数身份；分类器有效性另待复测 | 有据（指数身份） | 仅作候选信号，A 股有效性未验证（待复测） |
| regime 短均线 | 20 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:68` | [regime 研究论文](https://arxiv.org/abs/2208.11574)（200）证明可分段，不证明 20 | 未验证 | 建议待回测，不建议启用 |
| regime 长均线 | 60 个交易日 | 主线未实现；`src/backend/app/aggregates/service.py:68` | [regime 研究论文](https://arxiv.org/abs/2208.11574)（200）不规定 60 | 未验证 | 建议待回测，不建议启用 |
| regime 最少指数值 | 45 根 | 主线未实现；`src/backend/app/aggregates/service.py:68` | [NIST 样本量说明](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm)（200）不提供 45 的统一门槛 | 未验证 | 建议待回测，不建议启用 |
| regime 最少宽度值 | 15 个 | 主线未实现；`src/backend/app/aggregates/service.py:68` | [NIST 样本量说明](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm)（200）不提供 15 的统一门槛 | 未验证 | 建议待回测，不建议启用 |
| regime 防抖天数 | 2 | `config/risk_controls.yaml:17`；`src/backend/app/risk/settings.py:27-28` | [regime 研究论文](https://arxiv.org/abs/2208.11574)（200）不规定 2 日防抖 | 未验证 | 建议待回测，不建议启用 |
| `regime_ranges.uptrend` | `[60,90]`% | `config/risk_controls.yaml:13-15`；`src/backend/app/risk/settings.py:26-29` | [中证沪深300编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf)（200）不规定仓位区间 | 未验证 | 建议复核/补出处，不改默认值 |
| `regime_ranges.range` | `[40,60]`% | `config/risk_controls.yaml:15`；`src/backend/app/risk/settings.py:27` | [中证沪深300编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf)（200）不规定仓位区间 | 未验证 | 建议复核/补出处，不改默认值 |
| `regime_ranges.downtrend` | `[0,30]`% | `config/risk_controls.yaml:16`；`src/backend/app/risk/settings.py:27` | [中证沪深300编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf)（200）不规定仓位区间 | 未验证 | 建议复核/补出处，不改默认值 |
| `cooling_off_after_stop.enabled` | `false` | `config/risk_controls.yaml:40-42` | [FINRA 日内交易说明](https://www.finra.org/investors/investing/investment-products/stocks/day-trading)（200）是风险教育，不规定本系统冷静期开关 | 未验证 | 建议保持关闭，补出处 |
| `cooling_off_after_stop.days` | 3 个交易日 | `config/risk_controls.yaml:42`；`src/backend/app/config_files.py:618-620` | [FINRA 日内交易说明](https://www.finra.org/investors/investing/investment-products/stocks/day-trading)（200）不规定 3 日 | 未验证 | 建议待回测，不建议启用 |
| `same_template_cooldown_days` | 3 个交易日 | `config/risk_controls.yaml:43`；`src/backend/app/config_files.py:623-627` | [FINRA 日内交易说明](https://www.finra.org/investors/investing/investment-products/stocks/day-trading)（200）不规定模板冷却 | 未验证 | 建议复核/补出处，不改已启用值 |
| `new_listing_min_days` | 30 个交易日 | `config/risk_controls.yaml:39`；`src/backend/app/config_files.py:623-627` | [上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)（200）不支持本系统 30 日闸门 | 未验证 | 建议复核/补出处，不改默认值 |
| `rc5_loss_streak_drawdown.pause_days` | 5 个交易日 | `config/risk_controls.yaml:28`；`src/backend/app/config_files.py:573-579` | [FINRA 日内交易说明](https://www.finra.org/investors/investing/investment-products/stocks/day-trading)（200）不规定账户暂停 5 日 | 未验证 | 建议复核/补出处，不改默认值 |
| 复盘统计 `n` | 0 | `src/backend/app/strategy/promotions.py:220`；`src/backend/app/strategy/reviews.py:178` | [NIST 样本量说明](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm)（200）说明样本量取决于精度，不支持把 0 当可判定样本 | 未验证 | 保持 `null`/`small_sample`，不得启用结论 |
| 复盘 `small_sample` 阈值 | `n<30` | `src/backend/app/tracking/service.py:195,515`；`config/strategies/hold_risk_monitor.yaml:149` | [NIST 样本量说明](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm)（200）无统一 30 阈值 | 未验证 | 建议待回测并补统计出处，不放宽断言 |
| 复盘可显示下限 | `n>=5`，否则 value 为 `null` | `src/backend/app/tracking/service.py:186-195,507-515` | [NIST 样本量说明](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm)（200）无统一 5 阈值 | 未验证 | 建议待回测并补出处 |
| 复盘窗口 | `120 trading days` | `src/backend/app/strategy/promotions.py:220`；`src/backend/app/strategy/reviews.py:178` | [NIST 样本量说明](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm)（200）不规定 120 日窗口 | 未验证 | 建议回测窗口敏感性并补出处 |
| `outcome_metrics` 缺证状态 | 当前未生成可判定值，数据库字段可空 | `src/backend/app/db/tables/reviews.py:91`；日报投影 `src/backend/app/reports/service.py:363` | [NIST 样本量说明](https://www.itl.nist.gov/div898/handbook/prc/section2/prc222.htm)（200）不证明本系统结果指标口径 | 未验证 | 保持 `null` + 缺口，不建议启用 |

## 本轮结论

- 参数行共 63 行：有据 1 行（仅 `000300.SH` 指数身份），未验证 62 行。SSE、实时行情和风险管理公开资料未给出本项目具体秒数、轮数、比例或交易日阈值。
- 市场宽度、覆盖率和 regime 的公式、窗口、阈值与仓位区间仍是仓内候选定义。市场概览主线继续返回 `null`，不得把候选阈值写成已实现或已验收。
- 禁投冷静期默认关闭。已启用的同模板 3 个交易日仅建议复核并补出处，不改默认值。
- 复盘保持 `n=0`、`null` 与 `small_sample`，不放宽断言，不产生未来函数。
