# T-R102 市场概览指标口径卡

- `lifecycle: draft`
- 角色：策略研究员；输出是候选信号的研究输入，不是荐股或交易指令。
- 观察时点：只在 T 日收盘数据已发布且对查询时点可见后计算。
- 适用范围：默认“沪深股票口径”，不把北交所混入分母或两市成交额。

## 1. 与仓内字段对齐

仓内已经存在的市场概览字段如下。这里的仓内文件只是字段对齐依据，不是公开出处。

| 研究量 | 复用字段 | 当前形状 |
|---|---|---|
| 指数行情 | `MarketOverview.indices[*]` | `security_code`、`name`、`price`、`change_pct`、`amount`、`t` |
| 基础宽度 | `MarketOverview.breadth` | `up`、`down`、`flat`、`limit_up`、`limit_down` |
| 两市成交额 | `MarketOverview.turnover_total` | 十进制字符串，金额单位元 |
| 快照资格与缺数 | `MarketBasis` | `eligible`、`observed`、`trading`、`suspended`、`missing`、`mode`、`observed_date`、`source` |
| 个股日线输入 | `daily_bars`/收盘快照 | `trade_date`、`open`、`high`、`low`、`close`、`pre_close`、`volume`、`amount`、`is_suspended`、`fetched_at`、`is_final` |
| 证券分类 | 证券主数据 | `board`、`security_type`、`security_risk_flag`、上市日期与上市状态 |

本卡新增的研究派生量不改变上述 API 字段。`limit_up`、`limit_down` 在现有字段中保留总数，研究存储若拆桶，应另外保留 `regular`、`st_5pct_candidate`、`no_limit` 的审计分量，不能只保留一个合计数。

## 2. 共用计算边界

### 2.1 样本池和分母

- **默认池**：交易日 T 的沪交所、深交所股票及存托凭证，`security_type in {stock, cdr}`。ETF、指数、基金、债券不进入股票宽度。北交所（`*.BJ`）单列观察，默认排除，不混入“沪深股票口径”。
- **ST**：`security_risk_flag in {st, star_st}` 的股票仍进入上涨、下跌、平盘、均线、新高/新低等基础分母。涨跌停另按风险警示规则桶计数。
- **新股首日**：有有效 `pre_close` 且有成交时可进入上涨、下跌、平盘。因上市首日通常无涨跌幅限制，不进入涨停、跌停、炸板、连板。均线、新高/新低需要足够历史，历史不足就从相应指标分母删除。
- **停牌和零量**：`is_suspended=true`、确认无成交或 `volume=0` 的行不计上涨、下跌、平盘，也不计涨跌停。缺行不能推断停牌。`MarketBasis.suspended` 只统计有停牌事实的成员，未知成员进入 `missing`。
- **零值与缺值**：真实 `close=0` 或 `amount=0` 若上游明确给出则保留并按交易规则判定。`pre_close`、`close`、`volume` 或必要的规则字段缺失时，该证券从受影响指标中删除并记录缺口，不能补成平盘。

### 2.2 T 日收盘和可见性

- 交易日由交易日历确定，不能用自然日或“当前时间已收盘”替代。
- 个股收盘行须满足 `trade_date=T`、`fetched_at` 的北京时间不早于 T 日 15:00、`fetched_at <= query_as_of`，并且有上游正式收盘标记。仓内日快照继续遵守既有 `FINAL_AFTER=17:10` 门槛，未达到门槛的行不能当作收盘价。
- 指数收盘行须有 T 日正式收盘记录并满足 `t <= query_as_of`。盘中行即使查询发生在 15:00 后也不能改标为收盘。
- 所有滚动窗口只取 `trade_date <= T` 的已完成交易日。晚到修订只影响新快照，不能回填已经生成的 T 日候选信号。
- 涨跌幅统一为 `change_pct = 100 × (close - pre_close) / pre_close`。`pre_close <= 0` 或除权除息调整关系不明时，涨跌方向和涨跌停均为缺失。

## 3. 大盘环境：主要指数趋势

### 3.1 指数集合和价格输入

| 指数 | 研究代码（主代码） | 代表范围 | 公开编制/发布出处 |
|---|---|---|---|
| 上证综合指数 | `000001.SH` | 沪市符合规则的股票与存托凭证 | [上证系列指数简介](https://www.sse.com.cn/market/sseindex/overview/) |
| 深证成指 | `399001.SZ` | 深市成份股 | [深交所指数编制方案目录](https://www.szse.cn/marketServices/message/index/project/) |
| 创业板指 | `399006.SZ` | 创业板成份股 | [深交所指数编制方案目录](https://www.szse.cn/marketServices/message/index/project/) |
| 沪深300 | `000300.SH` | 沪深市场大市值、流动性较好的 300 只证券 | [沪深300指数编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf) |
| 中证500 | `000905.SH` | 沪深市场中小盘规模指数 | [中证500指数编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000905_Index_Methodology_cn.pdf) |
| 中证1000 | `000852.SH` | 中证800样本以外的规模偏小且流动性较好的 1000 只证券 | [中证1000指数编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208175402-000852_Index_Methodology_cn.pdf) |

输入字段为 `indices[*].price`、`indices[*].change_pct`、`indices[*].t` 和同一指数的历史正式收盘价。指数的成分调整不改变指数价格序列的时点要求。

### 3.2 均线和单指数状态

- **定义**：`SMA_n(T) = (C_T + C_{T-1} + ... + C_{T-n+1}) / n`，其中 `n ∈ {20, 60}`，`C` 是不复权的指数正式收盘价。`price_position_n = C_T / SMA_n(T) - 1`。
- **输入字段**：指数 `close`、`trade_date`、`is_final` 或等价正式收盘标记、`fetched_at`、`query_as_of`。
- **样本范围**：每个指数至少有连续 60 个已完成交易日才给出 20/60 日状态。缺一日不插值，窗口不足返回 `null`。
- **计算时点**：T 日收盘快照冻结后，使用截至 T 的窗口。T+1 及以后数据不能参与 T 日均线。
- **候选分档**：
  - `uptrend_candidate`：`C_T > SMA20(T)` 且 `SMA20(T) > SMA60(T)`。
  - `downtrend_candidate`：`C_T < SMA20(T)` 且 `SMA20(T) < SMA60(T)`。
  - `range_candidate`：其余情况，等号也归入此档。
- **边界**：复权方式、指数临时停牌、指数换基或编制方案调整造成的历史不连续须在快照中留证。分档阈值是均线关系的候选信号，未证明预测收益，标记**待回测**。[均线定义与市场宽度示例研究](https://github.com/anyuzhe/simple-quant/blob/main/docs/%E7%AD%96%E7%95%A5%E4%B8%8E%E5%9B%A0%E5%AD%90%E6%80%BB%E8%AF%B4%E6%98%8E.md)；该出处不规定本卡的 20/60 阈值。

### 3.3 六指数合成环境

- **定义**：对六个指数分别计 `bullish_i`、`bearish_i`、`range_i`，得到 `B`、`D`、`R`。
- **公式**：`trend_score = (B - D) / 6`。要求六个指数均有 T 日正式收盘和至少 60 日历史，否则 `regime=null` 并写入缺口。
- **候选分档**：`B >= 4` 且 `B > D` 为 `uptrend`；`D >= 4` 且 `D > B` 为 `downtrend`；其余为 `range`。这三个分档为研究候选信号，**待回测**，不直接驱动仓位或荐股。
- **边界**：指数同日无交易、指数数据晚到、价格或均线缺失时不按“上一日状态”补齐。沪深300、中证500、中证1000的指数样本空间与全市场宽度不同，不能把它们的成分数当作宽度分母。

## 4. 市场宽度和涨跌停

### 4.1 上涨、下跌、平盘家数

- **定义**：在有效成员集合 `E_T` 中，`up = count(change_pct > 0)`，`down = count(change_pct < 0)`，`flat = count(change_pct = 0)`。`N = up + down + flat`。
- **输入字段**：`close`、`pre_close`、`volume`、`is_suspended`、证券类型、板块和风险警示标志。
- **样本/时点**：按 §2 的沪深股票口径、T 日正式收盘。ST计入三类家数，停牌、零量、缺前收盘排除。新股首日只有在 `pre_close` 有效时计入。
- **派生比例**：`up_share=up/N`，`down_share=down/N`，`AD_ratio=up/down`。`down=0` 时 `AD_ratio=+∞`，`up=down=0` 时为 `null`。
- **候选分档**：`up_share>=60%` 且 `AD_ratio>=1.5` 为宽度偏强；`down_share>=60%` 且 `AD_ratio<=2/3` 为宽度偏弱；其余为中性。阈值**待回测**。公开页面支持家数的符号定义，不支持本卡阈值。[涨跌家数定义与日频收盘口径](https://data.bywl.top/temperature/)、[公开研究中的上涨家数占比案例](https://pdf.dfcfw.com/pdf/H3_AP202606021823164236_1.pdf)。
- **边界**：`N=0` 时所有比例为空，不能输出“平盘”。大盘指数上涨而 `up_share` 下降时保留两者，不用指数方向替代宽度。

### 4.2 涨停和跌停家数

- **定义**：先按 T 日生效交易规则计算 `limit_up_price`、`limit_down_price`，再计 `limit_up = count(close == limit_up_price)`、`limit_down = count(close == limit_down_price)`。价格比较按证券最小变动单位的交易所舍入规则，不能用浮点容差。
- **输入字段**：`pre_close`、`close`、`high`、`low`、`volume`、`is_suspended`、`board`、`security_risk_flag`、上市日期、T 日生效的涨跌幅规则及最小价位变动单位。
- **规则桶**：任务指定的候选研究桶为普通主板 10%、科创板/创业板 20%、北交所 30%，ST单独保留 5%桶。主板风险警示 5% 的公开历史规则见[深交所2023年主板问答](https://investor.szse.cn/knowledge/qa/t20230306_599093.html)和[深交所2021年规则通知](https://www.szse.cn/lawrules/rule/fund/trade/t20210331_585336.html)。上交所现行规则页面已写明主板 10%及科创板20%，深交所现行规则页面写明主板10%、创业板20%，分别见[上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)和[深交所交易规则](https://www.szse.cn/lawrules/rule/trade/current/W020260424690713155663.pdf)。
- **时效边界**：上交所、深交所已在 2026 年规则中调整主板风险警示规则。若 T 日处于规则生效日之后，必须使用规则表的实际生效比例，不能把历史 5% 固定套用。任务要求的 `st_5pct_candidate` 只作为历史回测或兼容分桶，当前适用性标记**待回测**。北交所 30% 的规则链接可见[北交所交易规则](https://www.bse.cn/jygl_list/200028217.html)，但本次 `curl -I -L` 返回 403，出处标记**未验证**，且北交所默认不进入本卡合计。
- **新股首日**：上市首日及交易规则列明的无涨跌幅日，不计涨停、跌停。无价格涨跌幅限制的证券不能通过 `close/pre_close` 反推“涨停”。
- **候选分档**：`limit_up - limit_down >= 30` 且 `limit_up > limit_down` 为情绪偏强；反向条件为偏弱；其余为中性。该家数阈值**待回测**，仅作候选信号。
- **边界**：一字封板仍只计收盘锁定，不推断可成交性。除权除息、价格最小变动单位、停牌复牌、退市整理期和上市首日必须用 T 日规则表逐行处理。没有规则证据时该行进入 `missing`，不能按主板10%猜测。

### 4.3 炸板率

- **定义**：`touched_up = count(high >= limit_up_price)`；`failed_up = count(high >= limit_up_price and close < limit_up_price)`；`炸板率 = failed_up / touched_up`。`touched_up=0` 时为 `null`。
- **输入字段**：`high`、`close`、`pre_close`、规则桶、最小价位变动单位、成交和停牌字段。仅对有价格涨跌幅限制且有完整高低收盘的股票计算。
- **样本/时点**：T 日收盘后计算，盘中曾触及涨停但收盘未封板才是分子。新股首日、无涨跌幅日、停牌、零量、规则缺失排除。ST按其实际生效限制分桶，不能与普通股混合解释。
- **候选分档**：`<20%` 为承接较稳，`20%–40%` 为分歧，`>40%` 为承接较弱。区间端点左闭右开，阈值**待回测**。[公开研究的炸板率代理公式](https://github.com/anyuzhe/simple-quant/blob/main/docs/%E7%AD%96%E7%95%A5%E4%B8%8E%E5%9B%A0%E5%AD%90%E6%80%BB%E8%AF%B4%E6%98%8E.md)。
- **边界**：仅有日线 `high` 而无规则价时不计算。收盘价因价格精度展示被截断时，必须使用原始十进制和 tick 舍入，不以展示字符串近似。

### 4.4 连板高度

- **定义**：对每只股票，从 T 向前回溯连续交易日，逐日满足“有价格涨跌幅限制且 `close == limit_up_price`”的最长连续长度，记 `streak_i`；`连板高度=max(streak_i)`。只统计含 T 日的连续段。
- **输入字段**：至少连续窗口内每个交易日的 `close`、`pre_close`、规则生效比例、上市状态、停牌和成交字段。跨规则变更日不得把不同限制比例拼成一段。
- **样本/时点**：T 日收盘冻结后，按当日及历史可见规则计算。新股无涨跌幅日、停牌日、规则缺失日会截断连续段，不向前跳过。
- **候选分档**：`0–1板` 为低，`2–3板` 为中，`>=4板` 为高；阈值**待回测**。连板高度只描述市场情绪，不代表个股可交易或未来收益。[公开研究对连板高度和炸板率的定义示例](https://www.ten-agent.cn/limit.html)。
- **边界**：同一股票发生 ST、摘帽、换板或规则变更时重新计算规则段。只剩一只股票的极端高度不能单独把环境判为强势，须与宽度、炸板率同时展示。

## 5. 成交额和量能

### 5.1 两市成交额

- **定义**：`turnover_total(T) = Σ amount_i(T)`，`i` 为沪交所和深交所有效股票及存托凭证成交行。金额单位为元。ETF、基金、债券和北交所不计入默认口径。
- **输入字段**：个股 `amount`、`volume`、`close`、`is_suspended`、证券类型、交易所；指数 `amount` 不能替代个股汇总。
- **样本/时点**：T 日正式收盘，按 §2 的可见性和停牌规则。`amount=0` 是真实零值时保留，缺失不补零。沪深任一市场全量缺失时，合计为 `null` 并记录缺口，不能用单市场数冒充两市。
- **出处**：公开研究将上证与深证逐日成交额相加作为沪深两市口径，[低成交额环境下的A股交易策略](https://www.jiuyangongshe.com/a/3fsklt1nl08)；该文为公开样本研究，不是交易所统计口径，字段可比性需持续核对，标记**待回测**。

### 5.2 与 N 日均值之比

- **定义**：默认 `N=20`，`MA_amount_N(T)=mean(turnover_total(T-k), k=0..N-1)`，`amount_ratio_N=turnover_total(T)/MA_amount_N(T)`。可配置 N 时必须把 N 写入快照。
- **输入字段**：过去 N 个交易日的 `turnover_total`、交易日历、每个快照的 `mode=close`、`observed_date`、`source`。
- **样本/时点**：只用 T 及之前 N 个已发布收盘快照。窗口不足 N、任一日合计为 null、或混入不同范围的成交额时，比例为 null，不用可得天数平均冒充 N 日均值。
- **候选分档**：`ratio < 0.80` 缩量，`0.80 ≤ ratio ≤ 1.20` 常态，`ratio > 1.20` 放量。公开研究使用 20 日均量并检验 `1.15` 倍条件，但没有统一行业阈值，本卡 0.80/1.20 与 1.15 仅为候选参数，均**待回测**。[20日均量研究](https://www.jiuyangongshe.com/a/3fsklt1nl08)。
- **边界**：节假日和停牌日按交易日窗口，不按自然日填充。更换成交额来源、纳入北交所或纳入 ETF 后必须重建历史窗口，不能跨口径拼接。

## 6. 新高、新低和均线宽度

### 6.1 新高/新低家数

- **定义**：默认回看 250 个已完成交易日，不含 T 日。`new_high = count(close_T > max(close_{T-250..T-1}))`，`new_low = count(close_T < min(close_{T-250..T-1}))`。严格大于/小于，等于不计。
- **输入字段**：个股 `close`、交易日历、历史正式收盘、上市日期、停牌和成交字段。新股上市不足 250 日从该指标分母删除，不用上市价补齐。
- **样本/时点**：默认沪深股票池，ST进入分母，停牌、零量、缺任一窗口值排除。只有完整 250 日历史的成员进入 `H_T`、`L_T` 分母，分别输出 `new_high_share`、`new_low_share`。
- **候选分档**：`new_high - new_low >= 100` 且 `new_high_share >= 5%` 为扩散偏强；反向条件为偏弱；其余为中性。数值和比例均**待回测**。[公开市场宽度研究对新高/新低扩散的定义示例](https://lianbanwang.com/rs.html)。
- **边界**：除权、拆并股和复权口径必须在全窗口一致。使用后复权价时必须明确标注，不能把不复权的 `close` 与复权历史混用。

### 6.2 站上 20/60 日均线占比

- **定义**：对有至少 N 个完整历史收盘的成员，`above_MA_N = count(close_T > SMA_N(T))`，`valid_N = count(有完整 N 日窗口的成员)`，`above_MA_N_share = above_MA_N / valid_N`，N 为 20 或 60。
- **输入字段**：个股 `close`、历史交易日、`is_suspended`、成交、上市日期及规则一致的复权标志。均线计算统一使用不复权或统一指定复权，不能逐股混用。
- **样本/时点**：T 日收盘后只用截至 T 的历史。ST进入分母，停牌、零量、窗口不足和缺历史的成员删除；新股首日及上市不足 N 日不计入相应 `valid_N`。北交所不计入默认分母。
- **候选分档**：对每个占比，`>=70%` 为宽度偏强，`30%–70%` 为中性，`<30%` 为偏弱。两个周期同时满足才可在候选信号中写“宽度一致”，否则只展示各自结果。阈值**待回测**；公开研究展示站上均线占比，但不规定统一分档。[市场宽度与均线占比示例](https://lianbanwang.com/rs.html)。
- **边界**：`valid_N=0` 时占比为 null。停牌不能以最后成交价继续计算“站上均线”，除非该日有正式收盘且交易状态明确。均线等号不计“站上”。

## 7. 组合展示和缺数

- 展示顺序为“六指数状态 → 上涨/下跌/平盘 → 涨停/跌停及 ST 分桶 → 炸板率 → 连板高度 → 两市成交额与 N 日比 → 新高/新低 → MA20/MA60 占比”。这只是候选信号的可读性安排，不是评分或荐股。
- 每个指标附 `observed_date=T`、`mode=close`、`source`、`eligible/observed/trading/suspended/missing`。不同指标的有效分母分别记录，不能把涨跌家数的 `N` 当作均线宽度的 `valid_N`。
- 任一关键来源未发布、规则表缺失、查询时点不可见或窗口不足，返回 null 并保留缺口。不要以当前时间、上一交易日、指数方向或单市场成交额替代缺失数据。

## 8. 公开出处可访问性登记

以下链接在编写本卡时用 `curl -I -L` 验证。北交所规则页因站点对该请求返回 HTTP 403，保留链接但标记“未验证”。研究网页和仓内字段都不能替代交易所的生效规则表。

| 编号 | 用途 | 可访问性 |
|---|---|---|
| R1 | 上交所交易规则，主板/科创板涨跌幅与无涨跌幅日 | 已验证，HTTP 200 |
| R2 | 深交所现行交易规则，主板/创业板涨跌幅与无涨跌幅日 | 已验证，HTTP 200 |
| R3 | 上交所科创板 20%及新股前五日 | 已验证，HTTP 200 |
| R4 | 深交所主板风险警示历史 5%及新股前五日 | 已验证，HTTP 200 |
| R5 | 北交所交易规则 30% | **未验证，`curl -I -L` HTTP 403** |
| R6 | 沪深300编制方案 | 已验证，HTTP 200 |
| R7 | 中证500编制方案 | 已验证，HTTP 200 |
| R8 | 中证1000编制方案 | 已验证，HTTP 200 |
| R9 | 上证系列指数发布说明 | 已验证，HTTP 200 |
| R10 | 深证指数编制方案目录 | 已验证，HTTP 200 |
| R11 | 20日成交额比研究 | 已验证，HTTP 200 |
| R12 | 成交额/上涨家数公开研究样本 | 已验证，HTTP 200 |
| R13 | 宽度、炸板率、连板高度定义示例 | 已验证，HTTP 200 |
| R14 | 新高/新低与均线宽度展示示例 | 已验证，HTTP 200 |

本卡共有 **13 个已验证出处**，**1 个出处未验证**。所有带“待回测”的分档都只是候选信号，不能写成已验证有效，也不能直接触发交易动作。
