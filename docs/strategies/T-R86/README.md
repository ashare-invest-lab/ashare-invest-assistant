# T-R86｜F09–F12 正式缺口与独立代理（待 T-A197 裁定）

20只×3日×4键=240行。正式 `value` 及原18列逐值保持上一轮不变，仍全部null；null不是0。
新增 `proxy_value/proxy_flags` 只给后端逐值对照用，**不是正式证据**，不代表生产接线或数值口径验收。
**本层沿用 T-R81 的 A01–A03 代理层先例，T-R86 是否适用待编排者确认，口径待 T-A197 裁定。**
仅解释候选信号，不荐股、不承诺收益；全行 `proxy_only;T_R86_applicability_pending;T_A197_pending`。

## 依据、正式层与输入

冻结T-R81 `f70789f2fd52d4654e3a45b442608e25ee43fda1` 的脚本/CSV（含T-R81c），T-R83 `5a0e745a` 的fq_options.md、T-R78 `dd683be9` §3.9–3.12；工作区基线 `3c0456ca`。
F键映射：F09=profit_cagr_3y（Q03–05）；F10=dividend_continuous_years（Q06–09）；F11=limit_up_count_20d；F12=fin_report_count（Q01–02）。T-R83 B9=F12/B11=F09/B12=F10。
正式层仍需 `available_at=max(披露次交易日09:30,首次真实可见,所有依赖可见)`，截至财务15:00/F11 15:05；源first_seen_at/available_at未知，故不准入正式值。
正式缺口：F09可比链/上市年龄；F10支付完成/闭合/中断年；F11日历/sf/pc除权参考/无限制日/逐日ST/15日门槛；F12完整历史/上市身份。北交所HG2门禁不解除。
全部20只沿用T-R81：600519、000001、600228、600825、600293、603159、603307、001225、688610、300502、300750、688981、688801、001246、001381、301569、301718、920000、920085、000972。
评估日事先沿用2026-06-30、2026-09-30、2026-11-09，CSV as_of为北京时间15:05，财务截至15:00。
[public_sources.csv](sources/public_sources.csv)保持原86行、44个URL及SHA256：40个东方财富公开接口、2个公告PDF、2个行情包；访问日2026-11-15。
[proxy_inputs.jsonl](sources/proxy_inputs.jsonl)每股一行，按fields对应数组保存完整响应的所需原字段；source_id回链原账本URL/响应SHA256。40份原始响应抽取前逐一校验哈希，成功接口pages=1且count等于返回行数；这些不证明历史完整性。
利润保留原始十进制文本；分红按每10股税前人民币字段。脚本锁定两个源文件及行情包SHA256，不在线重取；动态接口重取可能变化。
公告仅供正式缺口审计：000972的06-26公告涉及06-29撤销风险警示，11-03债权通知不能冒充实施公告；单点事件不能闭合历史身份。

## 代理规则与flags

- 公共边界：`calendar_proxy=sh000001_bars`，用包内上证指数观察日，非交易所日历；`listing_first_bar_proxy` 用首K作上市边界，上市前null=`before_first_bar_proxy`，不认证上市日。北交所null=`HG2`。
- 财务PIT：`deadline_notice_proxy`。NOTICE_DATE≤法定截止日时，`available_at_proxy=min(截止日次一交易日09:30,NOTICE_DATE次一交易日09:30)`；年报为次年4/30，Q1为当年4/30、H1为8/31、Q3为10/31。次日指上述指数日历的严格后一日，不是自然日。
- 期限出处沿fq_options F-Q01：[2021办法十二、十三条](https://www.csrc.gov.cn/csrc/c106256/c1653948/content.shtml)、[2025办法十三、六十七条](https://www.csrc.gov.cn/csrc/c101953/c7547359/7547359/files/%E9%99%84%E4%BB%B61%EF%BC%9A%E4%B8%8A%E5%B8%82%E5%85%AC%E5%8F%B8%E4%BF%A1%E6%81%AF%E6%8A%AB%E9%9C%B2%E7%AE%A1%E7%90%86%E5%8A%9E%E6%B3%95.pdf)，季度用沪/深5.2.1–2；本任务仅采用普通期限代理，未补全历史规则/延期版本（`deadline_notice_proxy`），期限不是真实披露证据。
- NOTICE_DATE晚于截止日，使用NOTICE_DATE次一观察日09:30，绝不倒填截止日，并加 `late_or_restated`。仅纳入jzrq≤d、NOTICE_DATE>jzrq、NOTICE_DATE≤d且available_at_proxy≤财务截止的报告；更正按jzrq去重，冲突版本报错。该时间是代理，不写入正式available_at列。
- 东财返回值可能经过重述，财务所有行（含null）一律 `restated_value_risk`；历史集合/上市身份未证加 `scope_snapshot_unverified`。即使日期筛选通过，也不能证明数值版本历史可见，不能宣称严格PIT已经成立。
- F09：`annual_endpoints`，按Q05最新可见年报y及y−3两端，`100×((NP_y/NP_(y−3))^(1/3)−1)`，Decimal最终HALF_UP到pct两位。Q04推荐基期≤0→`base_nonpositive`、末期=0→`end_zero`、末期<0→`end_negative`，不用有符号立方根；缺端点→`missing_endpoint`，不退旧年。Q02上市前报告排除仅用于F12，不删F09独立端点；首K上市不足三年→`listing_under_three_years_proxy`；可比链未证保留 `comparability_unverified`，不冒充Q03已验收。
- F10：`ex_date_proxy;fiscal_year;cash_only_no_buybacks`。仅筛NOTICE_DATE≤d、利润归属期≤d、状态实施分配、除息日已过日终及正额现金；公告提前可见但除息未到不计。每10股金额除10，同年度中期/特别/年度现金合并为一次，不计回购、送转或当前未实施方案。
- F10计数遵Q07：从最近一个已闭合利润归属年度往前数，明确闭合零年停止，遇未知则null；接口没有闭合/全覆盖/明确中断证据，不能把“最近有分红年”当起点。本快照因此无可准入的已闭合年，39行 `year_closure_and_break_unverified`；`observed_cash_years`只列已过除息日的正额年份，不是连续年数。空接口且证明不了从未分红为 `source_empty_not_zero`，其余无实施现金为 `no_visible_implemented_cash`；缺证不生成25等猜测值。
- F12：`distinct_jzrq`，仅统计上述时间可见且报告期≥首K上市代理日的不同jzrq；不把上市前比较数、预告、重复版本算新期。接口空/没有可见报告但未证完整空集→`no_visible_reports_not_proven_empty`，不填0；`scope_snapshot_unverified`表示这是接口集合计数，不是已证全历史报告数。
- F11：直接调用冻结T-R81 `proxy_context/proxies` 的B7分支；`raw_price;st_unverified`：原始前有效收盘×(1+当日market_rules比例)，HALF_UP到分，差不足一价位取前收+0.01；计数close_raw==涨停价，普通主板10%、创/科20%、北30%后执行HG2排除，不拿当前ST认定历史比例。
- F11 `threshold_unapproved`：指数W20内至少15个有效日，量>0、正价且OHLC自洽；`suspension_proxy=missing_bar`缺K占窗、不补0、不前填；`ipo_no_limit_proxy`依据首K与规则段剔除沪深前5/北首日，规则首段以前不倒套。`insufficient_window/invalid_evaluation_bar/limit_price_unavailable`均置null。flags的window含所用前收，valid_bars为剔除无限制日后的样本数。
- F11 `exdiv_heuristic_unverified`：有限制日abs(open/前有效close−1)>板块比例，上下跳空均视疑似除权；依赖区间含前收，命中置null=`excluded_exdiv_suspected`，事件记 `exdiv_suspected_dates`。不复权、不解码gbbq；小额现金除权可能漏检，代理值仍可能受未复权跳变影响。
- F11按T-R81c排除当前快照命中的000972全部三日：`st_current_snapshot_hit;gap=excluded_st_suspected;current_snapshot_exclusion_lookahead`。当前快照只用于减去代理值，**这是事后保守排除，存在前视**；T-R81特许不自动适用于T-R86，待编排者确认，后端不得照搬，必须用历史可见ST证据。其余未命中不证明历史非ST。
- F11逐行显式断言（ValueError，不依赖Python assert）必须等于冻结T-R81 CSV的B7 proxy_value，包含null；失败报告代码/日期/两边数值，不自动修正。普通和-O都执行。未来行情不参与窗口，未来报告/披露/除息不提前准入；上述当前ST排除与重述风险仍明确保留。

## 计数与手算边界

| 键 | proxy非空 | proxy null | 正式null |
|---|---:|---:|---:|
| F09 | 26 | 34 | 60 |
| F10 | 0 | 60 | 60 |
| F11 | 30 | 30 | 60 |
| F12 | 41 | 19 | 60 |

合计97个非空代理。F10缺闭合/中断证据，000972 F11按规则排除，不能满足这两项的非空手算要求；报告保留各两例拒绝过程，并补600228 F11两例非空值。
手算摘要：600519在06-30和09-30的F09均为100×((82320067101.68/62717467870.12)^(1/3)−1)=9.49%；F12分别1+23×4+2+1=96、1+23×4+3+2=98。分项可见日及F10/F11过程见团队报告T-R86b节。

## 离线复现

纯标准库；只读指定公开归档及冻结git对象，不访问网络、数据库、凭据或生产模块。需仓库含上述T-R81提交对象；缺失立即失败，不退回分支最新版本。
在仓库根目录将DATA设为两包所在目录（例如相邻tdx-pack）；不配置私有数据源：

```sh
DATA=../tdx-pack
export PYTHONDONTWRITEBYTECODE=1
python3 docs/strategies/T-R86/gen_reference.py --day-zip "$DATA/hsjday_20261110.zip" --gbbq-zip "$DATA/gbbq_20261110.zip" --rules config/market_rules.yaml
python3 docs/strategies/T-R86/gen_reference.py --check --day-zip "$DATA/hsjday_20261110.zip" --gbbq-zip "$DATA/gbbq_20261110.zip" --rules config/market_rules.yaml
python3 -O docs/strategies/T-R86/gen_reference.py --check --day-zip "$DATA/hsjday_20261110.zip" --gbbq-zip "$DATA/gbbq_20261110.zip" --rules config/market_rules.yaml
```

`--check`逐字节复现两层全部列；`--sources/--output`可另给路径，源哈希仍锁定。`--features F09`等仅替换所选键，两层同时重算；最终验收必须不带该参数。
正式层继续拒绝新出现但未复核的可见证据；代理源、规则或T-R81冻结版本改变须显式重审，不能用字节复现通过代替口径裁定。
