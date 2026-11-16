# T-R86｜B9–B12 离线参考（依 T-A197（契约 v1.0））

依据 `git show 2297d8f:docs/contracts/finance-inputs.md`，不再采用候选推荐口径。
20只×3日×4键=240行；正式 `value` 仍全部 null，原因使用契约内部码，可同时记录多个。
`proxy_value` 沿用 T-R81 先例，仅供离线对照；T-R86 适用性仍待编排者确认，不是正式证据或生产主源。
涨停计数见 T-R81 B7，不在契约范围内。

| 键及 CSV input_key | F-Q（均 Opt-A） | proxy 非空/null |
|---|---|---:|
| B9 `f.fin_report_count` | 01–02 | 41/19 |
| B10 `f.roe_ttm` | 01、03 | 38/22 |
| B11 `f.profit_cagr_3y` | 03–05 | 26/34 |
| B12 `f.dividend_continuous_years` | 06–09 | 0/60 |

原 F12→B9、F09→B11、F10→B12；新增 B10。评估日为 2026-06-30、09-30、11-09，CSV as_of=15:05+08:00，统一按当日15:00截止。
正式主源仍为契约指定因子；公开快照缺首见、历史版本、完整性及可比链，离线结果不补位正式值。

- 可见代理只取 NOTICE_DATE 的次一上证指数观察日09:30；派生值取依赖最大值，空值不伪造时点。法定期限不生成披露日，脚本已移除截止日/min逻辑。
- 指数观察日只作日历代理；上市日用 tdx 首K，上市前拒绝。所有财务行保留 `restated_value_risk`；历史数值版本仍未证，不宣称严格历史PIT成立。北交所 HG2 门禁保留在 proxy_flags。
- B9 仅用正式利润表接口（REPORT_TYPE_CODE=001），不收预告、快报、摘要；period_end、plrq均不早于首K，plrq须晚于period_end，按period_end去重。接口集合不证明全历史覆盖；未证空集合不能填0。
- B10：年报直接取NP，季报 `TTM=NP_YTD(P)+NP_FY(上年)−NP_YTD(P−4)`；`100×TTM/((E(P)+E(P−4))/2)`。期末/平均权益≤0分别拒绝，期初负但期末及平均正允许，负利润保留。缺分量不回退。
- B11：最新可见完整年报y与y−3、36个月；两端严格正，分别记录base_nonpositive/end_zero/end_negative；缺端点不退旧年，首K上市不足三年拒绝。B10/B11仅最终ROUND_HALF_UP至pct两位，计算精度50位。
- B12：仅实际现金股利，需发放日日终及完成证据；除息日绝不补付款日。本快照无完成、事件全覆盖、最终决议、闭合及明确中断年证明，因此全部null/payment_unconfirmed等，不把缺年当零、不以最近有现金年为起点。
- `ex_date_proxy_years` 为 F-Q06 Opt-B 独立列，只在B12行承载对照；除息日期只能改变事件代理，不能豁免F-Q07–08的归属、闭合、同年去重及中断证据，故60行均null。`observed_ex_cash_years`仅列正现金观察年，不是连续年数。
- `cash_distribution_plus_buyback_years` 为 F-Q09 Opt-B 独立列，全列null：未取得可靠的已支付股利加已实施回购批次/金额/支付自然年完整数据；B12行原因missing_component;coverage_unknown。两列均不进入B12，也不直接比较大小。

[public_sources.csv](sources/public_sources.csv)记录104条来源、62个URL及原始响应SHA256。保留原40个利润/分红接口与行情包；移除无关ST公告及股本包，新增21个资产负债表请求（含银行通用接口空响应）。
权益使用东财公开 `RPT_F10_FINANCE_GBALANCE`，000001使用 `RPT_F10_FINANCE_BBALANCE` 的 `TOTAL_PARENT_EQUITY`，币种CNY；不以总权益替代归母权益。字段语义未独立证实，所有B10保留source_semantics_unverified。
[proxy_inputs.jsonl](sources/proxy_inputs.jsonl)每股一行按fields抽取，source_id关联URL/原始响应哈希；收入原响应逐一验哈希后补REPORT_TYPE_CODE，资产负债表原响应另行归档，响应pages=1且count逐一对齐。归档访问日2026-11-15不冒充历史首见日。
脚本锁定两份来源文件、输入切片及可选原包的SHA256；只读取公开归档，无网络、数据库或凭据访问。日期筛选排除未来报告/披露/除息；当前响应可能重述的风险单列保留。

## 仓库内公开行情切片与离线复现

出处为通达信公开日线 `hsjday_20261110.zip` 与权息 `gbbq_20261110.zip` 文件，包日期均为 **20261110**；日线公开发布入口见来源账本 `https://data.tdx.com.cn/vipdoc/hsjday.zip`。入口可能更新，不代表当前远端内容等于冻结包；本次只使用本地冻结原包，未联网核验当前下载地址或内容。
日线原包 SHA256 见来源账本 `kind=day_zip`；权息原包 SHA256 为 `c1cbc818d748079aa79749393729dbcf378adf258a22734762d19b885ed0eeab`。

切片仅含公开证券代码及日期，不含私有样本、持仓、股东代码。CSV 为 UTF-8、LF、含表头；日期单位为自然日，格式 `YYYY-MM-DD`（中国市场本地日期），证券代码按六位字符串读取、保留前导零。

| 文件 | 列名、含义与单位 | 抽取规则 |
|---|---|---|
| [inputs/calendar.csv](inputs/calendar.csv) | `trade_date`：上证指数 sh000001 的日线日期，无价格单位 | 仅保留原始首日 1990-12-19（原算法下界），以及三类 proxy 输入中非空 NOTICE_DATE 在原日历下界至最大评估日 2026-11-09 内的次一观察日；次日也不得晚于最大评估日。排序去重后 771 日，末日 2026-11-03。 |
| [inputs/listings.csv](inputs/listings.csv) | `code`：证券代码，无量纲；`first_bar_date`：首根日线日期 | 仅 proxy_inputs 中 20 股，各保留原 `.day` 的首个日期；代码前缀 92/6/其余分别映射 bj/sh/sz。首 K 只是上市日期代理，不能替代正式上市证据。 |

`.day` 记录按 `<IIIIIfII` 解析，只使用第一字段 YYYYMMDD；不保存 OHLC、成交量、成交额等未读取列。日历是针对锁定 proxy_inputs 和三个评估日的稀疏依赖切片，不是完整交易日历；保留每个查询日期的真实次日及首日下界，才能保持 `bisect_right` 和历史披露排除规则。早年财务披露仍参与 B9，不能只保留 2026 年。样本股后续日线均未使用，故不保留。
当前 B9–B12 与 proxy_inputs **没有读取任何 gbbq 字段**，分红代理来自已冻结的公开分红快照。因此实际所需权息记录为零，不另存无用权息 CSV，也不能据此推断这些股票没有权息事件。`--gbbq-zip` 保留为可选原包哈希及成员核验入口，不替代付款/完成证据。

从仓库根目录执行以下命令即可离线复现；仅需 Python 标准库，不需要原包、网络或环境配置：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 docs/strategies/T-R86/gen_reference.py --check
```

可选重抽取：将两份冻结原包放在工作目录的 `tdx-pack/` 后执行（原包不入库）：

```sh
PYTHONDONTWRITEBYTECODE=1 python3 docs/strategies/T-R86/gen_reference.py --day-zip tdx-pack/hsjday_20261110.zip --gbbq-zip tdx-pack/gbbq_20261110.zip --extract-inputs
```

`--day-zip` 直接从原包提取后计算；加 `--extract-inputs` 才写入切片，可用 `--input-dir` 指定切片目录。`--check` 只读、逐字节校验全部列，不能与 `--extract-inputs` 同用；`--features B9`等只重算选定键，最终验收必须全量。旧 `--rules` 仅为CLI兼容，不参与财务计算。
手算、各层null分布、与cbc665b逐值差异及验收结果见团队报告T-R86c节。仅解释候选信号，不荐股、不承诺收益。

## 验收用途（编排者 T-R86c 裁定）

- 代理层是后端计算逻辑的验收基准：同一份输入下，后端计算结果必须与 `proxy_value` 逐值一致；代理层不是正式证据，也不替代主源。
- 正式值全部为 null，是 #225 契约在缺少可信主源时的规定结果。B12 在实现时用标为【虚构】的合成夹具验收，覆盖契约 F-Q06–F-Q09 的各条边界。
