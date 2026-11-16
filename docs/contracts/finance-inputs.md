# B9–B12 财务输入契约

版本：v1.0（2026-11-15，T-A197 裁定）；F-Q01–F-Q09 全部采用 Opt-A。
依据：T-R83 `docs/strategies/T-R83/finance_inputs_audit.md` §2–§7；T-R85 `docs/strategies/T-R83/fq_options.md`「共同定义」及 F-Q01–F-Q09。方案与契约固定路径分别为 `docs/plan-finance-inputs.md`、`docs/contracts/finance-inputs.md`。
范围：B9 报告期数、B10 归母 ROE TTM、B11 归母利润三年 CAGR、B12 现金分红连续年数；不含封板计数。
PIT：一切输入及证据均须 `available_at≤as_of`，并截至评估交易日 d 收盘可见；统一截点 `t=min(as_of,d收盘时刻)`，时间按带时区瞬时比较。

## 共同定义

- 财报键：`issuer_id,security_class,period_end,statement_type,version_id`；保留 `plrq,first_seen_at,source_url,content_hash,supersedes_id`，`period_end` 对应 `jzrq`。
- 财报 `available_at=max(披露次交易日09:30,first_seen_at,全部依赖证据可见时点)`；缺披露日、首见或日历覆盖即 null，不猜公告盘前时间，不启用仅披露日例外。
- 选 t 内最新有效版本；排序冲突或版本缺口影响结果即 null，不以旧版本绕过新版本缺证；派生值的 `available_at` 取全部依赖的最大值，更正不得改写旧时点结果。
- B9 `f.fin_report_count` 为全历史合格非占位利润表按 `period_end` 去重的非负整数；`plrq≤period_end` 丢弃，更正/比较数不增期，预告/快报/摘要不独立计期。
- 完整性证据须含截止时点、覆盖起止及缺口清单；覆盖未知为 null，完整空集合才为 0，不按上市年龄推算期数或只取最近12行。
- `NP=income.gsmgsyzzdjlr`（归母净利润），`E=balance.gsmgdqsyhj`（归母权益），`P` 为季度序号；金额须有限、同币种同单位且口径可比。
- `TTM(P)=NP_YTD(P)+NP_FY(上一年)−NP_YTD(P−4)`；年报 P 直接取全年 NP；缺分量、不足12个月或不可比即 null，不相加四份累计数。
- B10 `f.roe_ttm=100×TTM(P)/((E(P)+E(P−4))/2)`，单位 pct；期末 E≤0 或平均 E≤0 即 null，负利润保留；期初 E 负而期末和平均均正不另拒绝。
- B11 `f.profit_cagr_3y=100×((NP_FY(y)/NP_FY(y−3))^(1/3)−1)`，单位 pct；依 F-Q03–05 校验端点、跨度和上市年龄。
- B10/B11 仅在最终输出一步按 `ROUND_HALF_UP` 舍入至 pct 两位；分量、端点、比值保留精度；B9/B12 为非负整数，不把 null 当 0。
- B12 `f.dividend_continuous_years` 的事件键为 `issuer_id,security_class,plan_id,payment_tranche_id`，另存可见版本及来源；同事件仅取最新有效版本。
- `cash_per_share_gross` 为目标普通股税前人民币每股现金，每10股报价除10；正数才满足现金条件，纯送转为已知非现金，负额异常不当零；不同股本基数的合计仅用于年度正额判别，不代表持有收益。
- `Run(Y,cash)` 从 Y 向前逐年数已闭合且 `cash(y)>0` 的连续段，遇首个已闭合明确零年停止；Y 明确零才输出0；途中未知、缺明确中断年或无完整年度均 null。
- 主源仍为 B10 `factor/quality.roe_ttm`、B11 `factor/growth.profit_cagr_3y`、B12 `factor/dividend.dividend_continuous_years`；单位、窗口、语义、依赖或历史 PIT 缺证均 null，离线重算不自动替换主源，B10 不切 F44。
- 内部结果至少保留 `value,unit,available_at,dependency_version_ids,null_reasons`；缺证时 `value=null` 并保留原因，原始证据及离线对照分别留存，不伪造派生可见时点。
- ST/停牌不重置财务历史，B9 集合不限制其他项独立合格依赖；LG0/LG0B/LG3/LG4 等缺失处理及北交所既有门禁照旧。

null 原因码为本契约待实现的内部证据码（T-B176 承接实现、接线与逐入口验收，依赖 T-A199 方案合入），可记录多个；不扩充公开接口原因码枚举：

| 原因码 | 含义 |
| --- | --- |
| `missing_disclosure`、`missing_visibility`、`calendar_not_covered`、`not_yet_available` | 缺披露日、缺可见时点、日历缺覆盖、依赖晚于 t |
| `version_conflict`、`coverage_unknown`、`identity_unknown`、`rule_unknown` | 版本冲突/缺链、范围未知、身份/上市日未知、适用规则不明（仅审计空值，除非影响 B9 范围） |
| `unit_unverified`、`source_semantics_unverified`、`invalid_amount` | 单位/币种未证、主源窗口/语义/PIT 未证、非有限或异常负现金金额 |
| `missing_component`、`insufficient_ttm`、`incomparable_basis` | 缺依赖分量、不足12个月、可比链或调整桥接缺证 |
| `equity_end_nonpositive`、`equity_avg_nonpositive` | 期末权益非正、平均权益非正 |
| `missing_endpoint`、`base_nonpositive`、`end_zero`、`end_negative`、`listing_under_3y`、`invalid_span` | 缺端点、基期非正、末期零、末期负、上市不足三年、跨度非36个月 |
| `payment_unconfirmed`、`year_unclosed`、`attribution_unknown`、`event_class_unknown`、`dividend_unsplittable` | 支付未证、年度未闭合、归属不明、事件/股份类别不明、股利金额不可拆分 |
| `no_complete_year`、`no_known_break` | 无完整年度、连续段前缺明确零中断年 |

## F-Q01｜披露期限与法规版本

裁定：采用 Opt-A，每条报告绑定适用规则快照。
理由：逐报告留证可审计，法定期限不能代替实际披露或接收时点。
实现要点：保存 `exchange,board,report_kind,rule_version,article,effective_from/to,applicable_periods,rule_evidence_at`，按生效/过渡条款唯一匹配；普通年/半年/Q1/Q3 期限为期末加4/2/1/1个日历月，Q1 核验不早于上年年报，特别延期须适用公告；`deadline`/顺序仅供审计，不造 `plrq`、不因逾期删报告；规则不明记 null/`rule_unknown`，若报告类型或覆盖也不明则 B9 null/`coverage_unknown`。
未验证：U01A：全板块历史版本/特别延期映射未穷尽；北原站本次302循环，条号沿T-R83，未完成本次正文复核。期限并非法定接收时间。
出处：S01 第十二、十三条；S02a 第十三、六十七条；S03a/S04 §5.2.1–5.2.2；S05a §6.1.1–6.1.3。

## F-Q02｜上市前报告集合

裁定：采用 Opt-A，B9 仅收上市后正式定期报告。
理由：以可证上市身份划定集合，避免把上市前财务历史误作上市后持续披露期数。
实现要点：`doc_type∈{Q1,H1,Q3,FY}`，且 `period_end≥exchange_list_date`、`plrq≥exchange_list_date`；排除招股书及上市前挂牌报告，比较数不新增；保留 `listing_identity_chain,coverage_start,coverage_complete`，换码不重置已证连续身份，转板须证身份链/上市边界；身份缺证→null/`identity_unknown`，覆盖不明→null/`coverage_unknown`，完整空集合为0。
未验证：U02A：`period_end≥上市日`是拟选研究边界，不是法规规定的因子计数法；主源是否一致未知。
出处：S03a/S04 §5.2.1；S06a 第二条。

## F-Q03｜重述可比性

裁定：采用 Opt-A，逐分量校验可比链后离线重算 B10/B11。
理由：各版本均可见仍可能混用重述基础，逐项证据才能支持拼接。
实现要点：依赖保存 `accounting_basis_id,consolidation_scope_basis,profit_type,currency,unit,restatement_chain_id`；须公告/附注明示同基础或有逐项调整桥接及来源，同名自填 ID 不构成证明；最新可见版本匹配后按共同公式重算，链不齐/调整量未知/不可比→null/`incomparable_basis`；桥接按自身可见时点生效，不要求文件同日发布，不擅自剔除正常并购增长。
未验证：U03A：上述条文不定义本项目可比链ID或TTM算法，实际可用桥接证据及主源一致性未证。
出处：S13 第十二至十四条、第十七条；S03a §5.2.12；S06a 第四条。

## F-Q04｜CAGR 零及负末期

裁定：采用 Opt-A，B11 基期与末期均须严格为正。
理由：采用保守的正值复利解释，分别保留经济边界与数据缺失原因。
实现要点：令 `b=NP_FY(y−3),e=NP_FY(y)`；`b≤0`→null/`base_nonpositive`，`e=0`→null/`end_zero`，`e<0`→null/`end_negative`，缺端点→null/`missing_endpoint`；上市不足三年→`listing_under_3y`，上市日/身份不明→`identity_unknown`；正端点按共同公式，不输出零末期的−100%，不启用有符号立方根；未舍入值域为 `(−100,+∞)`。
未验证：U04A：这是EPS产品的公开先例，不证明主源归母净利润CAGR同样排除零末期。
出处：S09「多年 EPS 增长」章节；S08「公式」章节。

## F-Q05｜三年端点

裁定：采用 Opt-A，B11 使用最新可见完整年报 y 与 y−3 端点。
理由：年度锚点清晰且依赖较少，避免将三份年报的两年跨度误作三年。
实现要点：保存 `fiscal_year,period_start,period_end,dependency_version_ids`；y 为 t 内最新可见完整12个月年报，两个端点跨36个月、四个年度位置；缺端点→null/`missing_endpoint`，年度变更致跨度不符→null/`invalid_span`；不回退较旧 y，不改两年或 TTM，不强制中间两年进公式，未来年报不得预取。
未验证：U05A：从EPS迁移为归母净利润、主源具体年报锚点/单位仍未证。
出处：S09「多年 EPS 增长」章节；S08「期数与公式」章节。

## F-Q06｜现金实施事件日

裁定：采用 Opt-A，发放日日终届满且有实施完成证据才计入；Opt-B 仅作 `ex_date_proxy` 离线对照，不进正式值。
理由：提前发布的实施安排与除息均不能独立证明现金实际支付完成。
实现要点：必备 `cash_pay_date,completion_evidence_url,completion_seen_at,payment_status=completed`；`event_available_at=max(发放日当地日终,实施安排可见时点,完成证据可见时点)`，全部≤t 才纳入；分批须证目标股份各批完成；取消排除，延期/执行未知不闭合，所需年度缺完成证据→null/`payment_unconfirmed`，不得以登记日或除息日补位。
未验证：U06A：公开格式不保证每次现金支付另有完成公告，日终下限及完成证据要求是保守候选，覆盖率未证。U06B：除息等价实际付款无普遍依据；本代理不满足现规格实际实施证据要求，须专门裁定。
出处：S03a §5.3.6–5.3.8；S12b 第一部分三、四及三编制提醒1。

## F-Q07｜归属年度、起点与闭合

裁定：采用 Opt-A，按利润归属会计年统计，并以可证闭合年度计算连续段。
理由：决议到实施之间保留未知，避免用最近有分红年掩盖中断。
实现要点：`distribution_fiscal_year` 取实施公告；最新可见完整年报年度为 y0，年度分配决议未见时 `Y=y0−1`，含不分配决议一旦可见则 `Y=y0`，不因未实施回退；无 y0→null/`no_complete_year`；闭合须该年年报、年度最终决议、全部中期/特别/年度事件覆盖、已知方案全部完成或最终取消；未决补派/执行未知→`year_unclosed`，归属不明→`attribution_unknown`；全覆盖且明确无现金才记0，再算 Run，缺明确中断年→`no_known_break`；后续补派只从新证据可见后归回原年重算。
未验证：U07A：法规未定义本因子的年度闭合；y0/决议切换、完整性证明及后续补派处理是候选状态机，供应商映射未知。
出处：S12b 第二项（一）发放年度；S07 第七、八条。

## F-Q08｜中期、特别现金与同年合并

裁定：采用 Opt-A，纳入全部可证归属的普通股现金，同年只计一个连续年。
理由：实际中期现金应进入年度判别，特别现金仍须逐事件证明归属。
实现要点：`event_kind∈{annual_regular,interim,special}`，按 F-Q06 确认、F-Q07 归年，按事件键去重，`cash(y)=Σcash_per_share_gross`；年度方案含中期总额时只加本次新增额，无法拆解→null/`dividend_unsplittable`；特别分红不猜公告年，归属未知→`attribution_unknown`，事件/股份类别不明→`event_class_unknown`，影响所需年度即 B12 null；纯送转不计现金。
未验证：U08A：特别分红的统一分类/默认归属没有找到直接公开口径；本候选不设默认，要求逐事件证据。
出处：S07 第七条；S12a 一（一）1；S12b「发放年度、分配方案」章节。

## F-Q09｜回购与监管视同现金

裁定：采用 Opt-A，B12 仅实际股利；Opt-B 仅允许另名 `cash_distribution_plus_buyback_years` 离线对照，不填 B12。
理由：每股股利与回购的受益对象及统计目的不同，监管合计不能证明股利连续年数。
实现要点：仅 `event_type=cash_dividend` 入 cash，排除 `buyback,buyback_cancel`；仅有股利加回购合计且不可拆→null/`dividend_unsplittable`，不以总额/股本反造股利；已闭合纯回购年 cash=0，两者并存只合计股利；离线 Opt-B 另按支付自然年闭合、人民币总额统计已支付股利及已实施现金集中竞价/要约回购，批次去重、预案不计、注销不再计，缺金额/类别/支付年/完整性均 null，与正式会计年口径不可直接比大小。
未验证：U09A：主源是否混入回购及可拆分性未验证，监管名词相同不证明字段相同。U09B：监管比例统计并未定义连续年数，扩展为该离线指标及主源映射未验证，跨市场适用条款需另证。
出处：S12a 一（一）1、一（二）注2、二编制提醒2；S12b「分配方案」章节；S07 第十一条。

## 受影响入口与逐入口验收（L-042/L-043）

本 PR 文档范围为 `docs/plan-finance-inputs.md` 与 `docs/contracts/finance-inputs.md` 两份文档；下列为测试名建议，全部待实现、未验证。模块从 `src/backend/` 起算；现有入口存在不代表已接通 B9–B12，拟增函数一律由后端命名。
正式承接任务为 T-B176（后端，依赖 T-A199 方案合入），负责本节全部缺口的实现、接线与逐入口验收；拆分见方案中的「T-B176 内的拆分 PR1–PR6」。方案引用 `tasks/T-A199.md`，验证引用 `tasks/T-R86.md` 与 `reports/T-R86.md`；T-A199 仅交方案，不算实现已派单（L-046）。
同一份标为虚构的合成输入包须含财报/因子/事件版本、身份链、规则快照、日历、闭合证明及固定 d/as_of；各格式从同包派生，逐入口独立执行，不能用公共函数测试替代 HTTP、probe、SQL 或 Windows 验收。

| 字段 | 受影响入口及状态 | 建议测试名与验收重点 |
| --- | --- | --- |
| B9 `f.fin_report_count` | `app/features/horizon_financial.py` 计数函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b9_count`：上市边界/换码、占位/重复更正、缺披露/覆盖与完整空集合、期限不造公告日 |
| B10 `f.roe_ttm` | `app/features/horizon_vendor.py` 主源适配函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b10_vendor`：单位/窗口/PIT 缺证拒绝、负值保留、不切 F44 |
| B10 | 逐分量可比链与 ROE 离线重算函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b10_recompute`：TTM 展开、负利润、期末/平均权益边界、期初负仍合格、混重述拒绝、最终舍入 |
| B11 `f.profit_cagr_3y` | `app/features/horizon_vendor.py` 主源适配函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b11_vendor`：年报锚点/利润类型/单位/历史 PIT 未证均 null，无离线补位 |
| B11 | 年报端点与 CAGR 离线重算函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b11_recompute`：100→133.1 为10.00、零/负/缺端点、上市不足三年、非36个月、不回退及最终舍入 |
| B12 `f.dividend_continuous_years` | `app/features/horizon_vendor.py` 主源适配函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b12_vendor`：非负整数 years、闭合/支付映射缺证拒绝，不用本地事件填主源 |
| B12 | 现金事件确认函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b12_payment`：预案/发放日未终/缺完成/延期不生效，取消排除，分批范围与版本去重 |
| B12 | 年度闭合与 Run 函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b12_run`：Y 决议切换、跨年支付归属、未知/无完整年/无零中断年为 null、Y 明确零为0 |
| B12 | 类别归并与回购隔离函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b12_cash_only`：中期/特别/年度合并、含中期总额不重复、纯送转/回购不延续、拆分缺证 null |
| B12 | 两种另名离线对照函数：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_b12_offline_isolation`：除息代理及股利加回购只在另名离线输出，均不可写 B12 |
| B9–B12 | `app/features/pipeline.prepare`：现有，财务接线待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_pipeline`：统一依赖版本及最大可见时点，不绕主源拒绝 |
| B9–B12 | `app/strategy/horizon/inputs.collect`：现有，四字段未接通（T-B176：实现、接线与逐入口验收） | `test_ta197_collect`：显式内部 as_of 待接，逐字段保持 null 原因及可见证据 |
| B9–B12 | 同模块 `evidence` | `test_ta197_evidence`：证据与字段值、单位和版本一致，不为未知伪造数值证据 |
| B9–B12 | 同模块 `snapshot_id` | `test_ta197_snapshot`：同输入版本可重放，后见版本不改旧评估 |
| B9–B12 | `app/strategy/horizon/classifier.classify` | `test_ta197_classify`：分别参数化四字段 null/0/合法值，沿既有缺失封顶及评分 |
| B9–B12 | `app/api/v1/horizon.get_horizon_assessment`，`GET /horizon-assessments` | `test_ta197_horizon_http`：独立请求验证缺失、证据和评分传播 |
| B9–B12 | `app/research/content._fit` | `test_ta197_fit`：已填画像时的独立分类消费仍保留财务缺证 |
| B9–B12 | 同模块 `generate` | `test_ta197_generate`：候选解释消费同一截点结果，不制造财务事实 |
| B9–B12 | `app/api/v1/candidates._new_version` | `test_ta197_candidate_version`：经原版本生成链验收，不因存档把未知变0 |
| B9–B12 | 同模块 `create_candidate`，`POST /candidates` | `test_ta197_create_candidate_http`：从新增候选原路调用，缺证/合法值均与同包结果一致 |
| B9–B12 | 同模块 `create_version`，`POST /candidates/{candidate_id}/versions` | `test_ta197_create_version_http`：从新增版本原路调用，新证据不改旧版本 |
| B9–B12 | `app/research/content.write_snapshot` | `test_ta197_write_snapshot`：原存档入口保留 null 与证据，不把另名离线值写入正式字段 |
| B9/B10/B11 | `app/api/v1/security_financials.PlaceholderFinancialsReader.read`：占位，实读待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_financials_reader`：空数据不冒充完整历史，年报 ROE 不冒充 TTM |
| B9/B10/B11 | 同模块 `financials`，`GET /securities/{code}/financials` | `test_ta197_financials_http`：独立验证 as_of、可见版本及占位状态 |
| B10/B11/B12 | `app/api/v1/security_factors.PlaceholderFactorsReader.read`：占位，实读待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_factors_reader`：无主源证明不产正式值，保持占位状态 |
| B10/B11/B12 | 同模块 `factors`，`GET /securities/{code}/factors` | `test_ta197_factors_http`：经原 HTTP 守卫不暴露合成因子或伪造版本 |
| B9–B12 | 财报/因子/事件导入、版本存储与重算调度：待实现（T-B176：实现、接线与逐入口验收） | `test_ta197_ingest_versions`、`test_ta197_recompute_job`：各自验收晚导入、更正、来源隔离，不覆盖旧版本 |
| B9–B12 依赖 | `app/reports/dimensions.financial_pit`：现有，仅可见性校验 | `test_ta197_financial_pit`：次交易日下限/首见/缺日历，不以此证明财务公式已实现 |
| B9–B12 依赖 | `src/backend/app/financial_basis.TradingCalendar.next_day` | `test_ta197_next_day`：开休市、缺覆盖；不能按自然日猜可见下限 |
| B9/B10/B11 依赖 | `src/backend/probes/p11_gaps` 的 `analyze_fin_rows`、`classify_pit`、`batch_asof`、`compare_history` | `test_ta197_p11_fin_rows`、`test_ta197_p11_pit`、`test_ta197_p11_batch`、`test_ta197_p11_history`：各函数独立核验，旧宽松判据不能证明本契约 |
| B10/B11/B12 | `src/backend/probes/p06_factors.main`、`src/backend/probes/p11_gaps.main`：外呼入口，本次禁运行 | `test_ta197_p06_entry`、`test_ta197_p11_entry`：仅注入离线传输替身，无外呼且不自动补主源 |
| B9–B12 依赖 | `src/backend/probes/p13_analyze.analyze`、`main`：旧离线分析入口 | `test_ta197_p13_analyze`、`test_ta197_p13_cli`：各入口核验旧版本/除息线索不足以证明可比链或支付完成 |
| B10/B11/B12 存储边界 | `deploy/db/drill/sample-data.sql`、`deploy/scripts/db-restore-drill.sh`：隔离演练 | `test_ta197_drill_sql`、`test_ta197_restore_drill`：分别执行原 SQL/脚本，合成因子种子不作为正式值或 PIT 证明 |

上述分组行每个原入口分别执行并记录结果；共同场景均须包含正常、边界、缺数、依赖晚于 t、等价时区，以及补派/重述新版本不改旧 as_of。逐项保存实现版本、平台、测试名、通过/失败/跳过；未执行统一标「未验证」。
当前未发现直接实现 B9–B12 计算的 Windows/SQL 入口；不得以此推定其他入口已验收。后端落地时须复查 probe、CLI、Windows、SQL 及其执行链，新增入口逐一补表；Linux 离线结果不代表 Windows 或真实 SQL 会话通过。
遗留主源单位/窗口/历史 PIT/语义映射、U 编号各项及 S05a 正文复核仍未验证；本次仅裁定契约，不宣称正式值启用或功能测试通过。
