# T-R101 禁投与冷静期规则知识卡

> `lifecycle: draft` · `version: 1` · `G7 ☐`
>
> 本卡只产生“候选信号”的确定性过滤结果，不荐股，不自动下单。规则作用于买入或加仓方向，已持仓的卖出、减仓和风险提示仍照常求值。

## 1. 来源

以下来源均在 2026-11-21 用 `curl -I -L` 检查过，HTTP 状态为 200。交易所规则只用于确认市场状态、风险警示、退市整理期和停牌等事实，不能证明本卡的行为阈值。

| 编号 | 作者或机构 | 标题 | URL | 在本卡中的用途 |
|---|---|---|---|---|
| S1 | 上海证券交易所 | 《上海证券交易所交易规则（2026年修订）》 | https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml | 风险警示板、退市整理期 15 个交易日、停牌日不计入整理期 |
| S2 | 上海证券交易所 | 《上海证券交易所股票上市规则（2026年4月修订）》 | https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/mainipo/c/c_20260424_10816589.shtml | 风险警示、退市整理期的状态与生效边界 |
| S3 | 深圳证券交易所 | 《关于发布〈深圳证券交易所股票上市规则（2025年修订）〉的通知》 | https://www.szse.cn/lawrules/rule/repeal/rules/t20250425_613256.html | 深市风险警示和终止上市规则的公开入口 |
| S4 | 北京证券交易所 | 《北京证券交易所交易规则（试行）》 | https://www.bse.cn/uploads/6/file/public/202109/20210909101516_y5wn2y3ft9.pdf | 说明北交所是独立交易市场，本卡不纳入北交所 |
| S5 | Ryan Garvey、Anthony Murphy、Fei Wu；Duquesne University、University of Oxford、Shanghai Jiao Tong University | “Do Losses Linger? Evidence from Proprietary Stock Traders” | https://www.nuff.ox.ac.uk/Users/MurphyA/Do%20Losses%20Linger.pdf | 近期亏损后交易更激进的行为机制，不能直接给出本卡阈值 |
| S6 | Qi Bao；上海财经大学等 | “Effectiveness of price limits: Evidence from China's ChiNext market” | https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0287548 | 中国市场涨跌停与过度反应的研究背景，不能直接给出冷静期天数 |
| S7 | Jun Deng、Huifeng Pan、Hongjun Yan、Liyan Yang；对外经济贸易大学、DePaul University、多伦多大学 | “Disclosing and Cooling-Off: An Analysis of Insider Trading Rules” | https://jfe-journal.org/wp-content/uploads/Disclosing-and-cooling-off-An-analysis.pdf | 冷静期可能改变交易时点与风险的机制背景，不作为 A 股参数证据 |

S5–S7 只支持“设置暂停窗口值得检验”的假设。它们没有验证本卡的 10 日、30 日、3 日、2%、3% 或 1 日等具体值，因此这些参数全部标记为“未验证、待回测”。

## 2. 假设

1. 交易状态、风险警示和公告可见性是候选信号的前置约束。状态未知时继续生成买入候选会把数据缺口误当成可交易。
2. 最近连续亏损、单笔或单日大亏损、止损后立即回到同一标的，以及连续涨跌停后的追单行为，可能提高非计划交易和过度反应风险。短暂停止买入可以作为待检验的风险控制假设。
3. 证伪条件是样本外比较开启和关闭冷静期后的扣费后结果、回撤、交易次数和错过机会成本。n < 30 时只报“样本少”，不改变规则。

## 3. 数据与时点

| 字段 | 含义和用途 | 可见时点与边界 |
|---|---|---|
| `security.board`、`security.type` | 市场和证券类型 | 以 T 日已经落库的主数据为准。`bse`、ETF、基金、可转债、CDR 不在本卡范围 |
| `f.is_st` | ST、*ST 或退市标记 | 主数据在 T 日 18:00 后定版，最早 T+1 09:30 用于候选信号。历史状态按生效区间取值 |
| `f.is_delisting_period` | 是否处于退市整理期 | 与上项相同。不得以简称当前值回写历史 |
| `f.is_suspended` | T 日是否停牌 | 只认交易所或日线停牌字段。零成交量、缺 K 线和价格不变都不能单独推断停牌 |
| `f.list_days` | 上市以来的交易日数 | 主数据定版后使用。缺失按未知处理，不按 0 补齐 |
| `f.ann_risk_count_10d` | 近 10 个交易日风险关键词公告数 | 公告盘后更新，T 日新增记录最早 T+1 09:30 可见。标题分类为“立案调查”时即使计数窗口只有该条也触发 |
| `f.is_limit_up_close`、`f.is_limit_down_close` | T 日收盘是否涨停或跌停 | 日线收盘后可见。涨跌停判定使用不复权价格和当日有效规则 |
| `trade.net_return`、`trade.exit_reason`、`trade.security_id` | 已完成交易的扣费后收益、退出原因和标的 | 只有成交与费用均结算后才可触发冷静期。未结算交易不计入亏损序列 |
| `account.daily_net_return`、`account.nav_close` | 账户 T 日扣费后日收益和收盘净值 | 只使用 T 日收盘后已冻结账本。缺任一值时冷静期状态为未知 |
| `calendar.next_trading_day` | 交易日计数 | 以交易所日历计数，不把自然日或周末计入冷静期 |

求值时点固定为 T 日收盘数据和 T 日以前已可见的事件，最早执行时点为 T+1 09:30。盘中不得读取尚未收盘的涨跌停状态，不得用后来修订的公告或主数据重写过去的候选信号。

## 4. 禁投名单规则

### 4.1 作用域与优先级

禁投规则只阻断 `buy` 和 `add`。同一证券已有持仓时，`sell` 和 `reduce` 不被禁投规则吞掉。G-01 `gate_tradability` 已有对应原因码的检查项只写入 `gate_results` 并产出不可执行原因，不把候选信号 `state` 改为 `vetoed`。本卡其他真正的策略 veto 才使用 `vetoed`。关键字段为 `null`、过期或来源冲突时状态为 `insufficient_data`，买入计划也被阻断，不能按“没有命中”放行。多个原因并列记录，解除一个原因不能解除其他原因。

### 4.2 确定性规则

| ID | 触发条件（T 日可见） | 时长 | 解除条件 | 状态落点、原因码和字段边界 |
|---|---|---|---|---|
| B1 风险警示 | `f.is_st = true`，覆盖 ST、*ST 和退市标记 | 从首次可见日起持续 | 摘帽事件；且没有 B2、B4 等其他原因 | G-01 写入 `gate_results`，产出 `ST_OR_DELISTING`，不改为 `vetoed`。`null` 继续阻断。简称缺失不能推导为 `false` |
| B2 退市整理期 | `f.is_delisting_period = true` | 整个退市整理状态有效期 | 退市整理期不可解除 | G-01 写入 `gate_results`，产出 `ST_OR_DELISTING`，不改为 `vetoed`。不以 `listing_status=listed` 自动解除。交易所规则规定整理交易期限为 15 个交易日，但本卡不以 15 日强行解除。全天停牌日不计入整理期 |
| B3 停牌 | `f.is_suspended = true` | 停牌日 | 新的交易日快照明确 `f.is_suspended = false` 且有效 K 线可用 | G-01 写入 `gate_results`，产出 `SUSPENDED`，不改为 `vetoed`。状态缺失、零量、OHLC 相等或缺 K 线均不能推断停牌，统一记 `insufficient_data` |
| B4 风险公告或立案调查 | `f.ann_risk_count_10d >= 1`，或公告分类明确为“立案调查” | 风险公告仍在最近 10 个交易日窗口内 | 新快照中计数为 0，且立案调查记录不再处于有效窗口 | 这是本卡的策略 veto，可用 `vetoed`。公告字段缺失或过期时记 `KEY_DATA_MISSING` 并保持 `insufficient_data`。公告只有日期时按盘后记录处理，T 日盘中不可见。标题否定语、澄清公告和更正公告需按版本号去重 |
| B5 上市未满门槛 | `f.list_days < 30` | 直到上市交易日数达到 30 | `f.list_days >= 30` 且主数据未缺失 | G-01 写入 `gate_results`，产出 `NEW_LISTING`，不改为 `vetoed`。30 是待回测候选值。重新上市、转板或主数据断档时重新进入未知状态 |
| B6 不在 A 股范围 | `security.board = bse`，或 `security.type` 不属于普通 A 股股票 | 永久不生成本卡买入候选 | 只有证券被正确归类为沪深主板、创业板或科创板普通股票后才可重新判定 | 范围外证券不生成本卡候选，不进入候选信号 `state`。北交所单独适用其交易规则，本卡不跨市场迁移阈值。基金、ETF、可转债、CDR 同样排除 |
| B7 买入不可成交 | `f.limit_locked_up = true` | 当日买入候选失效 | 下一交易日形成新的、可验证的涨停状态且不再一字封板 | G-01 写入 `gate_results`，产出 `LIMIT_LOCKED`，不改为 `vetoed`。涨停价字段缺失或冲突记 `insufficient_data`，不得当作未封板。`f.limit_locked_down` 不阻断卖出方向。价格比较一律用不复权值 |

### 4.3 状态边界

- T 日 18:00 后才到达的风险警示、退市整理期和上市日数修订，只能影响 T+1 09:30 及以后，不得回填 T 日盘中候选。
- 证券从交易所列表消失、主数据缺失或字段版本冲突时，B1–B5 相关状态按未知阻断买入，不能把退市或数据缺失转成正常状态。
- 停牌复牌首日若有效 K 线不足指标预热要求，禁投可解除，但策略本身仍可为 `insufficient_data`。
- 解除某一原因后，必须重新计算全部 B1–B7。仍有效的 G-01 原因继续保留对应 `gate_results` 和不可执行原因，B4 等策略 veto 继续使用 `vetoed`。

## 5. 冷静期规则

### 5.1 计时口径

冷静期目标键为 `(account_id, strategy_key, security_id)`。账户级触发使用 `security_id = ALL`，同一账户下所有策略的买入和加仓均被阻断。设触发交易日为 D0，冷静期 N 个交易日是 D0 之后的 N 个交易日，D0+1 至 D0+N 均阻断，D0+N+1 09:30 起才可重新判定。卖出、减仓和止损执行不受冷静期影响。

多个冷静期取结束时间较晚者。冷静期期间再次发生同类触发，结束日从新的 D0 重新计算。冷静期记录不能由当前进程、会话或 SQL 读取结果继承为“已解除”；每次求值读取带版本和时间戳的账本。

### 5.2 确定性触发

| ID | 触发条件 | 默认时长 | 解除条件 | 所用字段 |
|---|---|---:|---|---|
| C1 连续亏损 | 同一账户、同一策略最近已结算交易连续 `closed_loss_streak = 3` 笔 `trade.net_return < 0` | `pause_days = 5` 个交易日 | 用户确认恢复，或暂停期满且无新的 C1–C5 触发 | `trade.net_return`、`trade.settled_at`、`trade.strategy_key`；原因码 `LOSS_STREAK_PAUSE` |
| C2 单笔大亏损 | 单笔已结算交易 `trade.net_return <= -single_trade_loss_pct`，默认 `single_trade_loss_pct = 2%` | 3 个交易日 | 同上 | `trade.net_return`、成交费用账本、结算时间 |
| C3 单日大亏损 | 账户 T 日扣费后收益 `account.daily_net_return <= -daily_loss_pct`，默认 `daily_loss_pct = 3%` | 3 个交易日 | 同上 | `account.daily_net_return`、`account.nav_close` |
| C4 止损后同标的再入 | 同一 `(account_id, strategy_key, security_id)` 完成原因为 `stop_loss` 的退出，仅在 `executability.cooling_off_after_stop.enabled = true` 时创建冷静期，期间同标的再次出现候选信号时阻断 | 默认 `enabled = false`；启用时 `days = 3` 个交易日 | 冷静期结束且新候选不再沿用旧交易计划 | `trade.exit_reason`、交易日、证券和策略键；仓内定义见 `config/risk_controls.yaml` |
| C5 连续涨停或跌停后 | 最近连续 `limit_streak_threshold = 2` 个交易日同一方向满足 `f.is_limit_up_close = true` 或 `f.is_limit_down_close = true` | `limit_cooldown_days = 1` 个交易日 | 下一交易日收盘后重新求值，且无 B1–B7 或其他冷静期 | `f.is_limit_up_close`、`f.is_limit_down_close`、交易日历 |

C1 命中按仓内 RC5 定义写入原因码 `LOSS_STREAK_PAUSE`。C2–C5 命中写入原因码 `COOLING_OFF`。所有原因都保存 D0、结束交易日、触发字段的 `data_as_of` 和版本。原因码只表示候选信号被规则阻断，不表示收益预测。

### 5.3 冷静期数据边界

- 未结算交易、费用缺失、账户净值缺失和交易日历缺失时，不猜测盈亏或到期日，状态为 `insufficient_data`，买入候选阻断。
- 现金分红、拆并股和除权不改变已结算交易的扣费后金额。收益分母使用该笔成交的原始不复权名义金额，不能把后来的复权价格代入。
- 同一成交的部分成交合并为一笔已结算交易后再计数。撤单、未成交委托和纸面浮盈亏不计入 C1–C4。
- C5 只看已完成日线。盘中临时封板不提前开始冷静期，T 日收盘状态最早 T+1 09:30 可用。
- 禁投与冷静期同时存在时，展示全部原因，执行优先级为 `insufficient_data` > `vetoed` > `LOSS_STREAK_PAUSE` / `COOLING_OFF`。任何缺数都不放行买入。

## 6. 参数与敏感性

| 参数 | 候选默认值 | 敏感性范围 | 参数出处与状态 |
|---|---:|---:|---|
| `risk_window_days` | 10 交易日 | 5 / 10 / 20 | S1–S3 说明风险警示和公告边界，但没有 10 日窗口规定。**未验证、待回测** |
| `listing_min_days` | 30 交易日 | 20 / 30 / 60 | S2、S3 是上市规则公开出处，但没有本卡 30 日门槛。**未验证、待回测** |
| `closed_loss_streak` | 3 笔 | 2 / 3 / 4 | 仓内定义（`config/risk_controls.yaml` 的 RC5 `closed_loss_streak: 3`）；行为效果 **未验证、待回测** |
| `single_trade_loss_pct` | 2% | 1% / 2% / 3% | S5 是亏损行为机制证据，不给出 2% 阈值。**未验证、待回测** |
| `daily_loss_pct` | 3% | 2% / 3% / 5% | S5 是亏损行为机制证据，不给出 3% 阈值。**未验证、待回测** |
| `pause_days` | 5 交易日 | 1 / 3 / 5 | 仓内定义（`config/risk_controls.yaml` 的 RC5 `pause_days: 5`）；行为效果 **未验证、待回测** |
| `same_security_cooldown_days` | 3 交易日 | 1 / 3 / 5 | S5 支持避免亏损后立即加码的机制，不给出同标的 3 日值。**未验证、待回测** |
| `limit_streak_threshold` | 2 个交易日 | 2 / 3 / 4 | S6 研究连续涨跌停与过度反应，但不验证 2 日门槛。**未验证、待回测** |
| `limit_cooldown_days` | 1 交易日 | 1 / 2 / 3 | S6 支持连续涨跌停后重新评估的机制，不验证 1 日值。**未验证、待回测** |

敏感性分析按上述范围逐项变动，其他条件固定。报告至少拆分主板、创业板和科创板，剔除 B1–B7 命中记录，保留被过滤数量和错过机会成本。未完成样本外回测前，不把任何一组值标为已验收。

## 7. A 股约束

- 市场范围是沪深主板、创业板和科创板的普通 A 股股票。北交所、基金、ETF、可转债、CDR 和其他证券类型不在本卡范围。
- 所有天数均为交易日，时区为北京时间（UTC+8）。T 日盘后确认，最早 T+1 09:30 形成候选信号。
- A 股 T+1 约束只限制当日买入部分的卖出，不得用冷静期阻断必要的卖出或减仓。涨跌停和一字板导致的不可成交在执行层单独记录。
- ST、*ST、退市整理期和风险公告状态按生效日期取历史版本。不能用当前简称、当前交易所列表或最新公告重写历史样本。
- 涨跌停、停牌和成交价格均使用不复权字段。前复权序列不能参与 B7、C5 或任何绝对价格比较。
- 规则只读 T 日及以前已可见数据。盘中未收盘字段、T+1 才发布的公告和之后修订的主数据都不可进入 T 日候选信号。

## 8. 失效条件与当前缺口

1. 样本外 n ≥ 30 后，冷静期组相对于无冷静期组的扣费后回撤、连续亏损概率或交易次数没有改善，且机会成本显著上升时，C1–C5 的对应参数失效，需重新回测或撤销。
2. 风险公告标题分类对“立案调查”“更正”“回复函”等语义的精确率或召回率未达预设门槛时，B4 只能标为 `insufficient_data`，不能降级为无风险。
3. `security_risk_flag`、`listing_status`、停牌字段或账户结算账本缺少历史版本时，历史验证存在前视风险，结论不得用于参数确认。
4. 交易所规则、风险警示分类、涨跌停制度或北交所边界发生变更时，先更新来源和字段生效段，再冻结新版本。旧版本不被静默改写。
5. 本卡仍是 `draft`，G7 尚未勾选，9 个数值参数均未验证且待回测。仓内已有的 G-01、N-01 和同模板同证券 3 日冷却只作为对齐口径，不构成本卡的外部参数证据。
