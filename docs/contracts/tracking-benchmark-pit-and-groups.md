# 跟踪基准 PIT 与生成时置信度分组契约（T-A201）

## 0 定位与依据

本契约将已评审 `.codex-input/T-A191-draft.md` 的 G2、G3 分别交给 T-B173、T-B174；不另写 G1，生命周期沿 T-B171。
这是后端目标契约，不是实现完成声明；带 U 编号的建议须按 §6 确认后实施，不据此宣称现有接口已支持。
本次仅新增本文，不改既有契约正文、src 或 tests，不提交、不推送；不读写 .env/密钥，不调麦蕊。

| 引用文件 | 已逐项核对的章节 | 对本契约的依据 |
| --- | --- | --- |
| [api-contract.md](../api-contract.md) | §7.11.3（含 T-A27、T-A33(1)），存在，原节仍标 draft | 观测唯一键、冻结、补算、缺基准、Stat、匿名统计 |
| 同上 | §5.2，存在 | 建议内容不可变、逐策略版本结论及置信度 |
| 同上 | §7.4，存在 | 版本跟踪端点、scope、现有 by_horizon 响应 |
| [plan.md](../plan.md) | §2.8、§2.8.1，分别存在 | 版本×期限×动作×置信度统计、入场及排除口径 |
| [daily-bars-source.md](daily-bars-source.md) | §1、§2，分别存在 | 来源字段、fake 限 test、未知行情不补造；旧描述须结合后续契约 |
| [daily-bars-tdx.md](daily-bars-tdx.md) | §2、§4，分别存在 | 单行来源保真、tdx_local 的下游隔离 |
| [daily-snapshot-from-bars.md](daily-snapshot-from-bars.md) | §14、§14.1，分别存在 | 逐行 F、final、历史替换后的可见性及 owned 就绪边界 |
| [mairui-same-source-final-replace.md](mairui-same-source-final-replace.md) | §2、§6，分别存在 | 北京时间 17:10 含等号、新 F、不继承旧证书/时刻 |
| [trading-calendar-exrights.md](trading-calendar-exrights.md) | §2、§3、§4（含 §4.2）、§5、§6，分别存在 | 日历覆盖、时区、qfq 锚、因子版本、停牌、晚到不回写信号 |

上述指定章节无缺失；草稿转引的 `.codex-out/T-B171-rulings.md` 原件未找到，见 U01，不把转述当原件核验。
已先读 `src/backend/app/tracking/{service,engine,api,worker}.py`，草稿涉及的函数均存在，入口逐项见 §4。
已读 `app.marketdata.daily_snapshot._bar_item`、`_include_historical`，以及 `app.suggestions.models.Conclusion` 的 `signal` 类型 `SignalInput`；其 `confidence.level` 存在。
现状差异：`instrument` 仅按 fetched_at 截断、硬置 is_final=True，丢失来源/停牌；`run_one` 与 `_evaluate` 仍截到 D 日末；策略端点只按期限汇总。
`app.db.tables.market.daily_bars` 已有 source、source_licence_id、fetched_at、is_suspended，没有 available_at 或数据版本列；本文不假设已有这些列。

## 1 共同 PIT 约束

1. D 为该条观测到期业务日，as_of 为 T-B171 提供的本次作业截点；G2 不另算补算窗口，G3 不推进窗口。
2. 每个输入版本必须证明 available_at≤相应 as_of；日期或哈希不证明可见性，未知时点不能当已知，缺值 null＋gap，不补 0、不补因子 1、不跨日借价。
3. bar 同时满足 trade_date≤D；facts、分钟、因子及其版本分别校验可见时点，不能把 first_seen_at 当一切输入的唯一证明。因子有效日≤D 的补充限制见 U06。
4. 时间戳须带时区，按同一瞬时比较，业务日期取 Asia/Shanghai；日历缺自然日不推定休市，不按星期补齐，停牌不减少交易所开市日。
5. complete/untradable/excluded 冻结，complete 即使缺基准也不解冻；unavailable 的窗口、晚跑和历史保留由 T-B171 负责，本文只消费其结果。
6. 旧建议、日报、信号及已写快照不可改写；新观测另写快照并更新当前指针，历史只供审阅，不计入统计。补算与“不补跑过去信号”的边界见 U07。
7. 所有验收使用合成证券、日历、行情、因子、授权证据和连接替身/隔离临时库；零外呼，不以真实数据或供应商可用性为前提。

## 2 G2（T-B173）：基准及共用日线输入

### 2.1 输入版本门禁与定稿

- `app.tracking.service.instrument(conn, code, end, cutoff)` 签名已核实：end 对应 D，cutoff 对应本次 as_of；具体接线随 T-B171/T-B172 合入复核，不新增无出处参数。
- SQL 筛选不能代替逐版本校验；`app.tracking.engine._evaluate` 的基准入口和 raw 留证入口须执行相同门禁，直接传入合成字典也不能绕过。
- mairui 行以自己的 trade_date 判定：带时区 fetched_at≥该日 `daily_snapshot.FINAL_AFTER`（17:10）才 final，等号有效；15:00 收盘不等于定稿。
- 历史行仍对照自己的日期，不对照作业当天；final 合格不豁免 fetched_at/available_at≤as_of，不能把未来取得的完成版用于过去截点。
- fetched_at 仅在可证明是该版本首次可引用时刻时充当 available_at 的等价证据（U04）；不得把非空字段直接当证明。
- 替换行取新 source、source_licence_id、fetched_at，不继承旧 F；没有旧版本时历史重放留缺口，不从当前库行倒造旧版本。
- 日线基准使用引擎确定的入场日 open 与 D 日 close；任一端点缺失、不合格或停牌，基准收益、超额及方向依赖值为 null＋gap，保留仍可算的标的收益。
- 上述日线端点规则仅适用于现有盘后路径；盘中仍按既有下一分钟入场口径，不能借日 open 补分钟缺口。
- 标的 qfq 价格使用同一 as_of 的因子与版本，锚按日历契 §4.2；不拼接不同锚点末值，不将 raw 成本与 qfq 混算。

### 2.2 来源与停牌保真

- tdx_local 不进入本契约的跟踪价格输入；fake 仅用于隔离合成测试，不成为正式行情来源。
- 正式路径推荐仅接纳来源授权可验证的 mairui；空来源、未知授权留缺口。tracking 的独立准入/证书绑定细则仍是 U03，不能照搬 owned 规则为已定事实。
- source、source_licence_id、fetched_at/first_seen_at、is_suspended 及所用版本证据按原值留存，不把不同来源拼成一行。
- 先判停牌再判 OHLC；is_suspended=true 即使 OHLC 平价且为正也不能定价，原始证据保留停牌状态和 suspended 缺口。
- 缺行、零量不证明停牌，状态未知不能默认为 False；状态与行情矛盾时不得据正价格输出可交易结论。

### 2.3 元数据落点与 gap 清单

复用 `run_one` 写入的 `data_snapshots.items` JSON：`raw_stock`、`raw_benchmark` 留逐行来源/版本/停牌证据，`as_of` 留本次截点，`results` 留当前观测。
复用现有 `canonical`、`digest` 和快照 `hash` 校验完整性；原行内容摘要作版本标识仅为 U05 方案，不新建数据版本列，不以哈希替代时点证据。
新元数据仅写新快照 JSON，不迁移、不加表/列；旧快照不补字段，原 hash 不变。候选被拒的原因须可追溯，raw 留证不能重新使其成为可定价输入。

| 情形 | 复用的 gap / 状态标识 | 输出边界与出处 |
| --- | --- | --- |
| 基准端点缺失，或时点/final/来源门禁不合格 | `benchmark_prices` | `_evaluate` 已有 key；相关指标 null，message 区分原因，不另造细分码 |
| 标的 qfq 端点或因子不足 | `qfq_prices_or_factors` | `_evaluate` 已有 key；`prepare` 的 `adjust_factor_missing:<date>` 保留原因，不补 1 |
| 有效日 K 缺失/非完成版 | `daily_bar_missing:<date>` | `prepare` 与日线快照契已有缺口；不得把原始留证行算有效 K |
| 明确停牌 | `suspended` | 原始 instrument gaps 的 reason、既有 exclusion_reason；不是擅增 `GapReason` 枚举 |
| 可交易性未知 | `tradability.is_suspended`、`tradability.limit_locked_up`、`tradability.limit_locked_down` | `_evaluate` 已有 key，不将未知状态转 False |
| 被动 hold 依据未知 | `forced_hold`、`t1.is_suspended`、`t1.limit_locked_down` | `_evaluate` 已有 key；沿原排除规则 |
| 日历缺覆盖/尚无观测 | `calendar_not_covered`、`tracking_not_computed_or_calendar_not_covered` | 前者为日历契缺口；后者为 `view` 的既有 key，不互换为“休市” |
| 缺路径端点/部分路径日 | `qfq_path_endpoints`、`qfq_path_missing_sessions` | `_evaluate` 已有 key，保留原路径指标口径 |

跟踪 `Gap` 复用 key/reason/message；`app.tracking.engine.gap` 当前 reason 为 no_source，不把上表所有标识误当 reason 枚举。
本单不实现 T-B151 同源替换、C1 导入、补取或 owned 快照重建，不造指数行情/因子，不改 owned 就绪闸，不扩大真实源准入。

## 3 G3（T-B174）：策略版本×期限×动作×生成时置信度

### 3.1 分组键与生成绑定

- 完整分组键为 strategy_version_id × horizon_days × action × 生成时 confidence.level；期限沿 1/5/20，不把全期限汇总当动作统计。
- 保留现有 by_horizon 各项含义；草稿建议在每项新增 `by_action_confidence[]`，元素使用 `action`、`confidence_level`（high/medium/low/null）及现有统计/计数字段，见 U09。
- 从 `suggestions.snapshot_id` 指向的不可变 `tb75-suggestion-input-v1` 的 `input.conclusions`，精确匹配 result.strategy_version_id＋result.instance_id。
- 先核 owner/hash、版本/实例一致，以及 input.data_as_of、signal.created_at≤建议生成时刻；取 signal.proposed_action 与 signal.confidence.level，动作须与当前 result.action 一致。
- 不取合并置信度、不读当前候选信号或可变实例配置、不按当前 confidence.value 重新分箱；生成后修订不得改变分组。
- 同版本实例沿 `bind_instances` 已选结果：生成绑定实例 created_at 最早者，并列 id 最小；聚合只验证选中实例，不重选。
- 缺生成快照、置信度或可验证绑定，归 confidence_level=null 并列 gap `generation_confidence`（U10），不猜 low、不填 0、不回填旧建议。
- gap 登记：key=`generation_confidence`，经 `app.tracking.engine.gap` 构造（reason 沿 no_source，message 为既有前缀加 key）；含义：该观测的生成时置信度、生成快照或实例绑定缺失或不可验证，因此归入 null 置信度组。出处：编排者 11-16 裁定 U10；现有 gap key（§2.3 表）均为价格/日历/可交易性含义，无可复用者，故新登记。
- owner/hash 冲突沿现有拒绝路径；不得当作普通缺置信度继续返回跨归属数据，不能用 null 分组掩盖冲突。

### 3.2 当前结果与读时聚合

- 只读 `suggestion_tracking.snapshot_id` 当前指向的已提交快照及其 as_of；沿 `(suggestion_id, strategy_version_id, horizon_days)` 去重后分组，JSON 历史不入 n。
- T-B171 更新当前指针后下次读取自然反映新结果；GET 不补算、不写历史、不取行情，不建统计表或迁移，不实施健康度/自动降权。
- `scope=mine` 仅本人；`scope=site` 仅登录用户可见的策略级匿名数字。任何分组不得返回原始结果、个股、用户/账户/实例标识或生成快照内容。
- 复用 `stat`、`profit_loss`：n 按每项实际有效值分别计算，不用总记录数；pending/unavailable/untradable/excluded 不入有效 n，wait/被动 hold 依引擎排除。
- sell/reduce 收益不取反；盈亏比只用 buy/add/hold 的非零有效收益，无亏损样本为 null＋`no_losing_samples`；有亏损无盈利且 n≥5 时为 0。
- 每个 Stat 在 n<5 时 value=null、n<30 时 small_sample=true；测试覆盖 n=0/4/5/29/30。真实计数 0 合法，不能用它替代缺失观测。
- 空期限仍保留既有 by_horizon 结构；推荐其 by_action_confidence=[]，不生成动作×置信度的空笛卡尔积（U09）。
- 已有观测但无有效指标的组仍可显示：各 Stat 的 n=0、value=null、small_sample=true，状态计数如实；复用 pending_count/untradable_count/excluded_count，不新增 unavailable_count。
- max_loss_streak 沿现有完整观测顺序与算法，不当 Stat 改阈值；无观测时为真实计数 0。分组排序及旧快照缺失响应见 U09/U10。

## 4 受影响入口与验收

以下函数/端点均已在源码确认；测试名均为待新增设计，本次没有实现或执行这些测试。
实施者须先在原实现上运行对应 `test_tb173_*` / `test_tb174_*` 见红，记录预期断言失败，再修至绿；不能用导入失败或夹具故障代替见红。
新测试模块必须登记 `tests/ci-groups.yaml`：纯计算/连接替身归 parallel；使用实际隔离 PG 的归 serial_pg，风险未确认者保守串行；本次不修改该文件。
各用例均执行 §1 的合成与零外呼约束，transport/socket 外呼探针断言 0；不访问真实数据库、证书、行情或 .env。

### 4.1 T-B173 入口

1. `app.tracking.service.instrument`（直接修改）。
   - `test_tb173_instrument_final_boundary_not_close_time`：Given 同日 F 在 17:10 前/等于/之后及跨日历史行；When instrument；Then 逐行判 final，收盘不硬置 True。
   - `test_tb173_instrument_version_after_asof_or_unknown_is_gap`：Given 未来/无证据时点、新 F 替换、trade_date>D；When instrument；Then 均不能倒灌过去，等于截点且证据合格者可见。
   - `test_tb173_instrument_source_and_suspension_preserved`：Given 合成 mairui、tdx_local、空源、未知授权、fake、平价停牌及零量正常行；When instrument；Then 来源门禁按 U03、fake 仅 test、元数据原值保留，停牌无有效价，零量不推断停牌。
2. `app.tracking.engine.evaluate` / `_evaluate`（公共包装及直接求值入口）。
   - `test_tb173_benchmark_and_raw_share_version_gate`：Given 直接传入不合格版本/非 final/停牌行；When evaluate 与 _evaluate；Then 基准和 raw 定价留证均不可绕过门禁，拒绝依据可追溯。
   - `test_tb173_benchmark_missing_endpoint_no_cross_day_fill`：Given 入场日 open 或 D 日 close 缺失、邻日有价而标的完整；When 求值；Then 基准收益/超额/方向 null＋benchmark_prices，标的收益仍可算。
   - `test_tb173_retry_ignores_post_due_bars_and_factor_events`：Given D 后 bar、D 后事件及晚到 D 行；When 同一作业 as_of 求值；Then bar 不越 D，因子边界按 U06 确认结果，raw/qfq 同截点且不补 1。
3. `app.tracking.service.run_one`（写入/接线），`canonical` / `digest`（复用校验）。
   - `test_tb173_raw_snapshot_preserves_source_version_suspension`：Given 合格与拒绝候选版本；When run_one；Then 新 JSON 可核所用来源、版本、停牌、截点及 hash，无列/迁移，留证不会变成有效价。
   - `test_tb173_complete_snapshot_unchanged_after_source_replacement`：Given complete 缺基准、旧 hash 及后到替换行；When 再运行；Then 终态/旧快照/hash 不变，不新增历史，其他可补算观测消费 T-B171 截点。
4. `app.tracking.worker.tracking_task`（集成回归，生命周期不另实现）。
   - `test_tb173_worker_uses_lifecycle_cutoff_without_fetch`：Given T-B171 合成窗口内/外及首次晚跑场景；When tracking_task；Then 按已确定 D/as_of 接线，不另补偿窗口、不调用采集。
5. `app.tracking.service.calendar`、`app.tracking.engine.due_date`（只复用）。
   - `test_tb173_calendar_hole_does_not_invent_due_date`：Given 缺自然日、已知休市、个股停牌；When 计算 D 并接线；Then 缺覆盖保留 gap，已知开市计数不因停牌减少。
6. `app.marketdata.daily_snapshot._bar_item` / `_include_historical`（只对照规则）。
   - `test_tb173_final_and_visibility_match_daily_snapshot_rules`：Given 合成行覆盖 F 边界；When 对照 instrument 与两函数；Then final/历史截点一致，owned 就绪闸和当日窗口不变。

### 4.2 T-B174 入口

1. `app.tracking.api.strategy_tracking_view`；GET `/strategies/{strategy_id}/versions/{version_id}/tracking`（直接修改，API §7.4 的 id/vid 是同一路由占位符）。
   - `test_tb174_groups_action_by_generation_confidence`：Given 多版本/期限/动作/生成置信度交叉组合及空集合；When GET；Then 四维隔离、顺序稳定、旧汇总不变，各指标组 n 之和与汇总 n 一致，空集合按 U09 返回 []，不把组均值直接相加。
   - `test_tb174_confidence_ignores_later_signal_mutation`：Given 生成绑定不变而当前信号/配置被改；When GET；Then 分组不变，且未来 data_as_of/created_at 不作为生成时已知输入。
   - `test_tb174_missing_generation_confidence_is_null_gap`：Given 旧快照缺置信度/生成快照/实例绑定；When GET；Then 按 U10 返回 null 组和 gap，不猜 low；owner/hash 冲突仍拒绝。
   - `test_tb174_groups_mine_site_privacy_and_get_readonly`：Given 两用户及私有版本；When mine/site/未授权 GET；Then 归属与匿名白名单正确，返回不含标识/个股/快照内容，写入与补算调用均为 0。
2. `app.tracking.service.stat` / `profit_loss`（复用）。
   - `test_tb174_group_stat_thresholds_and_exclusions`：Given n=0/4/5/29/30、未知指标、各非 complete 状态、wait/被动 hold、sell/reduce、零收益和无亏损分母；When 分组统计；Then 每指标 n/阈值/排除正确，收益不反号，无亏损 null＋no_losing_samples。
3. `app.tracking.service.bind_instances`（选择规则对照，读时不重选）。
   - `test_tb174_groups_dedupe_instances_and_retry_history`：Given 同版本多实例及补算历史；When 当前结果分组；Then 保持最早实例/并列最小 id 的既有选择，每唯一键只计一次，历史 n 不叠加。
4. `app.tracking.service.results_for` / `view`（当前指针回归）；`app.tracking.api.suggestion_tracking_view`；GET `/suggestions/{identifier}/tracking`（本人明细回归）。
   - `test_tb174_current_results_refresh_without_history_or_get_writes`：Given unavailable 更新当前指针且旧历史保留；When results_for、view、两类 GET；Then 只反映当前结果、历史 hash 不变、本人明细与匿名统计一致，GET 零写入/零补算。

既有回归依据（已核实定义，不代表本次已跑）：`test_benchmark_future_revision_is_not_historical_knowledge`、`test_missing_benchmark_factors_calendar_and_future_knowledge`、`test_placeholder_rows_ignored_by_price_readers`。
聚合回归依据：`test_actual_p1_worker_tracking_snapshots_api_replay_pit_and_ownership`、`test_actual_multiple_strategy_versions_are_independently_persisted`、`test_api_ratio_reads_persisted_engine_observations_and_excludes_n`；这些均不能代替新增边界验收。

## 5 与 T-B171/T-B172 的依赖与顺序

实施前先确认 §6 涉及的口径；T-B171 负责 D/as_of、D+1…D+5、首次晚跑、终态冻结、当前/历史 JSON 及指针约定，本文不重开 G1。
按本任务明确要求，**T-B172 合入后才实施 T-B173/T-B174**；T-B172 的内容和当前合入状态见 U02，不能假定它已经修好任一入口。
合入后重新核对函数签名、快照结构和当前指针语义，再实施 T-B173 输入门禁与 T-B174 读时分组；G3 可用合成结果验证，但联合验收须使用 G2 真实接线。
最终联合验证晚到可见性、冻结、当前统计刷新、生成置信度不变和匿名边界；不能用旧硬置 final 路径宣称端到端通过。

## 6 未验证与待裁定清单

按 U01–U12 去重计 **12 项未验证**（含 §7 两项估算）；指定章节和函数存在性已核实，不计入未验证数。
U01–U10 已由编排者 11-16 裁定按下表执行（/workspace/team/tasks/T-A201-ruling.md）；U01、U02 保持硬依赖，T-B171、T-B172 合入后由架构师逐条复核一次。U11、U12 仍未验证，不阻断。

| 编号 | 原未验证项 | 已裁定（编排者 11-16） |
| --- | --- | --- |
| U01 | T-B171 裁定原件缺失，①–⑤仅见草稿转述 | 以合入后的 T-B171 与 API T-A33(1) 核对；D+5 含末次补算、D+6 冻结及首次晚跑一次沿原单，不在 G2/G3 自造规则 |
| U02 | T-B172 具体职责、合入状态及接口差异未验证 | 保持“合入后实施”的硬依赖，合入后复核，本文不猜其实现内容 |
| U03 | tracking 基准正式源准入、授权证据及证书绑定未验证 | 仅准入有可验证授权的 mairui；tdx_local/空来源/未知授权留缺口，fake 仅合成；不能据 source_licence_id 非空推定授权 |
| U04 | fetched_at 与版本首次可引用时刻的等价证据未验证 | 仅有逐版本证明才等价；否则不可见，替换必用新 F，不继承旧 F，不倒造旧版本 |
| U05 | 原行摘要作版本标识及 JSON 具体表示未验证 | 在新快照 JSON 保存所用原行内容与摘要，复用 canonical/digest；具体键名先对齐 T-B171/T-B172，不新增列，摘要只证明内容 |
| U06 | 因子事件有效日≤D 为草稿补充，日历契 §4.2 当前按 date≤as_of 北京日期 | 对本模拟观测推荐另限事件有效日≤D，同时 available_at≤as_of；保持既有 qfq@as_of 锚与版本隔离，不改全局 prepare 语义 |
| U07 | 补算使用本次 as_of 与快照契 §14/日历契 §6 的“不补跑历史”表面冲突 | 仅 API T-A33(1) 未完成模拟观测为例外；不重建建议/日报/信号，不放宽 owned 就绪条件，complete 缺基准也冻结 |
| U08 | 草稿对齐表“其余 done”可能覆盖未到期 pending / 既有 not_applicable | 仅解释为到期待补算分支；保留原分支及 result.pending 原义，complete/untradable/excluded 全冻结；由 T-B171 解决 |
| U09 | by_action_confidence、confidence_level 响应及稳定顺序未验证，API §7.4 尚无此字段 | 推荐增量嵌套、保留旧数组；仅输出有观测组，空集合 []；按既有 Action、ConfidenceLevel 枚举顺序且 null 最后，确认后发布 |
| U10 | 旧快照缺置信度处理及其专用 gap key 未验证，草稿未给码名 | 推荐沿已验证 result.action 归 null 置信度组，复用 Gap 结构保留缺失原因；gap key 定为 `generation_confidence`（见 §3.1 登记行），不放过 owner/hash 冲突 |

## 7 估算与拆单

| 后端单 | 实现净增 | 测试净增 | 合计 | 验证状态 |
| --- | --- | --- | --- | --- |
| T-B173 | 约 250 行 | 约 460 行 | 约 710 行 | U11：未验证，沿草稿估算，含 CI 登记的实际差量实施后复核 |
| T-B174 | 约 220 行 | 约 380 行 | 约 600 行 | U12：未验证，沿草稿估算，含 CI 登记的实际差量实施后复核 |

两单当前估算均≤800；实际任一超 800 必拆，不能压缩测试规避。T-B173 拆为“输入门禁/final/来源＋单元验收”和“JSON 留证/接线/冻结＋集成验收”；T-B174 拆为“生成绑定/缺失/去重＋单元验收”和“端点分组/隐私/阈值＋集成验收”，每片均保留先红后绿及 CI 登记。
本次文档验收运行 `python3 scripts/ci/check_contract.py`；该脚本仅检查既有 API/plan 静态一致性，不覆盖本文业务实现，后端新增用例仍待后续单执行。
