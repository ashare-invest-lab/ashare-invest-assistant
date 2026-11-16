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
脚本锁定两份来源文件与行情包SHA256；只读取公开归档，无网络、数据库或凭据访问。日期筛选排除未来报告/披露/除息；当前响应可能重述的风险单列保留。

```sh
DATA=../tdx-pack
export PYTHONDONTWRITEBYTECODE=1
python3 docs/strategies/T-R86/gen_reference.py --day-zip "$DATA/hsjday_20261110.zip"
python3 docs/strategies/T-R86/gen_reference.py --check --day-zip "$DATA/hsjday_20261110.zip"
python3 -O docs/strategies/T-R86/gen_reference.py --check --day-zip "$DATA/hsjday_20261110.zip"
```

`--check`逐字节校验全部列；`--features B9`等只重算选定键；最终验收必须全量。旧--gbbq-zip/--rules参数仅为CLI兼容，不参与财务计算。
手算、各层null分布、与cbc665b逐值差异及验收结果见团队报告T-R86c节。仅解释候选信号，不荐股、不承诺收益。
