# PN-03 交易日历与权息对齐契约（T-A160 第②部分）

## 1. 定位与范围

状态：主线契约草案，基线 main `f0914c3`；已裁定口径照用，新增接线与存储选择待 §11 裁定，不代表实现或启用。对齐日历、事件可见性与 qfq@as_of；不启用未验证算法，不改策略卡，不导真实全量。PN-06 合成闭环见 [post-close-synthetic-loop.md](post-close-synthetic-loop.md) §1–§7。

依据：[multi-source-ingest.md](multi-source-ingest.md) §2.1–§2.6、§3.4、§5 C5/C8、§6；[daily-snapshot-from-bars.md](daily-snapshot-from-bars.md) §14；[daily-bars-source.md](daily-bars-source.md) §10；[plan-next.md](../plan-next.md) §6 第 1 项、§7；团队 `reports/T-A159.md`「*_qfq 口径裁定」、`reports/T-A158.md`「编排者裁定」、`reports/T-A153.md`「裁定落实」。代码核对只证明当前接口，不等于真实数据已验证。

## 2. 日历主源、核对源与补齐范围

| 项 | 契约 |
| --- | --- |
| 主源 | DS `sessions.merged_calendar`：2026-08-07 及以前用 HF metadata 的 `market_calendar.csv`，之后用 `config/trading_calendar.json`，sha256 与 DS `runner_data.CALENDAR_SHA` 一致；两段重叠须一致。分界是日历分界，不套用分钟文件的分段日期 |
| 核对源 | hsjday sh000001 的交易日集合仅核对，不定义日历；保留主源独有日、指数独有日及覆盖区间差异清单。差异未解释前不得宣称核对一致，不据指数补写或删改主源开市日；麦蕊年历不直接换主源 |
| 业务日历 | 消费者使用合并结果进入 `market.trading_calendar` 后的覆盖与 is_open；每个已覆盖自然日须有开/休市状态，不能只写开市日、把缺行当休市 |
| 验证日历 | 证书/接口验证消费者成功，只证明该次验证；不证明业务日历已经补齐，不更新业务覆盖结论（S05） |
| 补齐 | T-T81 所述库日历目前只有 2026 年，本单未连库复测。按 C8 另单补 2022 起历史日历，推荐沿用 S05 的 T-B153；上界仅到经核对的主源覆盖范围，未知未来保持缺口 |
| 可审阅产物 | 来源与版本摘要、sha 核对结果、覆盖起止与未覆盖年份、重叠冲突和指数差异清单；合成验收不宣称真实文件已核验。真实数据前置沿 T-B143w，不由本契约执行 |

## 3. 交易日、时区与现有入口

以合并日历中 is_open 为真的日期为交易日，时区统一 Asia/Shanghai；时刻比较必须带时区，先按同一瞬时比较，业务日期取北京日期。个股停牌不改变交易所开市日定义。`OwnedDailyBarsReader.read` 或 `prepare` 对停牌有效 K 的处理不等于日历删日。

| 入口 / 情形 | 关系与失败语义 |
| --- | --- |
| `src/backend/app/aggregates/calendar.py` 的 `seed_calendar` | 接受已核对覆盖区间与开市集合，写入区间内各自然日。现有函数可更新 is_open，不能拿它绕过合并源的重叠一致性检查；本单不执行播种 |
| 同文件的 `market_clock` | 只读业务库日历，不外呼、不按星期兜底。覆盖外或覆盖内缺日期均为 `calendar_not_covered`；已知休市日按现有逻辑找前一开市日，不能混同未知日期 |
| `build_owned_snapshot`、`_sessions` | 历史窗口内缺任一自然日则保留 `calendar_not_covered`。前置 `covered` 对未知当日抛出带 CALENDAR_NOT_COVERED issue 的错误、对已知休市返回假；集成层须保留缺覆盖原因，不能把异常吞成已知休市 |
| 未来/跨年 | 不从指数缺行、工作日或验证成功推演开市；覆盖不足仍为 `calendar_not_covered`，不得输出依赖该窗口的可执行结论 |

## 4. 权息可见性与价格尺度

### 4.1 库存与事件

行情表只存不复权，adj_type 为 none，不存 qfq/hfq 序列；沿多源契 §2.5 / §3.4。gbbq 事件只取 e≤t，一次计算只用一个明确的 snapshot_sha256，不混快照。参考价缺失、非正或北交所没有事件支持时保留 `adjust_factor_missing`，不补 1。多源契的连乘式仍为「未验证，默认不生效」，C5 落地前快照缺因子口径照旧；本契约不以公式已写出代替算法验证。

事件进入该 T 的因子还必须满足 available_at≤as_of；事件发生日不是首次可见时刻，fetched_at 也不自动等于事件 available_at。派生因子必须可追溯所用快照和可见事件版本，不能把晚到事件包进一个伪造早时点的因子。

**存储缺口**：多源契 §3.4 未列 available_at；当前 `market.ex_rights_events` 有 registered_at，却没有 available_at（代码核对 `src/backend/app/db/tables/market.py`）。registered_at 与首次可引用时刻是否等价**未验证**。实施前须定义 available_at 的来源、时区、与 as_of 的比较规则及修订版本保留方式；无证据不得填事件日零点、导入前的历史时刻或其他默认值。

推荐定义见 §11 Q3：以事件版本首次进入所用 gbbq 快照并可供该次计算引用的时刻为 available_at，时区 Asia/Shanghai，按带时区瞬时比较。该定义尚未验证/裁定；在此之前，无 available_at 或无可验证等价时点的事件不得作为已可见输入交给 `prepare`，记录因子缺口，不补 1。

### 4.2 qfq@as_of 与展示锚

| 项 | 已裁定约束 |
| --- | --- |
| `prepare` | `src/backend/app/features/pipeline.py` 的 `prepare`：价格 = raw(d)×A(d)/A(T)，T 为 as_of 的北京日期；因子候选只取 date≤T 且 available_at≤as_of。缺可用因子记 `adjust_factor_missing:<date>`；不补 1。纯计算函数不负责采集或推断事件时点 |
| `*_qfq` | qfq@as_of：信号日锚定，每个 T 独立重算，只用当时可见权息；有有效原价及因子时 T 日值等于原价。用于信号、指标、逐个历史 T 独立调用 `prepare` 的回测及展示 |
| 展示锚 | 以晚于信号日的最新日锚定整列再切片，只准展示；禁止进入信号/回测，禁止拼接不同锚点末值计算指标。展示与信号路径显式区分，不改现有 `*_qfq` 名称 |
| 绝对价阈值 | 低于某元、一字板、涨跌停价等一律使用不复权价，不随 qfq 锚点改变；不在本单新增阈值 |
| 版本不可变 | 不使用后续修订的因子版本回写过去信号；历史 T 重放须复用当时可见快照/版本。新版本只影响符合可见时点的后续计算 |
| 入场与成本 | `plan.entry_price_qfq`、`ctx.cost_price_qfq`、`ctx.highest_close_since_entry_qfq` 沿 T-A159 的同尺度规则；不将 raw 成本与 qfq 价格直接混比 |
| 冻结结构位 | `plan.stop_loss_qfq` / `plan.breakout_level_qfq` **尚未实现**。若实现，持久化「不复权价位 L_raw(s) + 冻结日 s」，每个 T 派生 L_raw(s)×A(s)/A(T)；不得持久化某日 qfq 数值后跨除权日直接比较，不宣称本单已落地 |

## 5. 停复牌、新股与北交所

| 对象 | 处理 |
| --- | --- |
| 停复牌 | 沿多源契 §2.6：麦蕊 sf 为 1 原样写 is_suspended（平价 OHLC、零量额）；通达信/HF 不写占位，不据缺行推断停牌；零成交不等于停牌。复牌是否可交易要看当时可见状态，不能仅看恢复有行；停复牌不影响日历开市日 |
| 新股 | 上市日前没有行情不得补造；上市日是否交易日看日历，是否可交易不得仅凭缺行推断。listing_history 等仍仅是多源契 §6 的核对清单，覆盖与时点「未验证」，不把未核上市日表提升为已就绪主源 |
| 北交所代码 | 沿多源契 §2.1、源契 §10；旧码不改写、不合并；错后缀仅只读盘点方案，本单不盘真实行 |
| 北交所单位 | 按 T-A158 已裁定：先用 tdx_local 离线对算至少 20 只北交所股票，单位一致后乘 100 换成股再写库。对算和写库均非本单实施；已有单只样本不能替代此前置 |
| 北交所权息/历史 | gbbq 不含 BJ 事件，qfq 保持 `adjust_factor_missing`，不补 1；单次 history 行数上限与分页仍只能称「未见截断」，未验证完整覆盖 |

## 6. 失败与缺口语义

| 情况 | 输出与禁止行为 |
| --- | --- |
| 日历缺覆盖、重叠冲突或 sha 不符 | 缺覆盖用 `calendar_not_covered`；冲突/校验失败保留差异证据、停止采用该候选日历，不自动修复。不得报告补齐成功 |
| 缺因子、未知事件可见时点、缺参考价 | 对受影响日期输出 `adjust_factor_missing:<date>`、相关值为空；不补 1，不以前值掩盖未知事件。已有明确有效累计因子的查找沿 `prepare`，不额外要求每日存一条因子 |
| 缺 bar / 非完成版 bar | 沿快照契 §14 的省略与有效 K 缺口；同源完成版替换归 [mairui-same-source-final-replace.md](mairui-same-source-final-replace.md) §2–§6 / T-B151，不在 PN-03 实施 |
| 停牌、不可交易或状态未知 | 保留状态/缺口，不编造可交易或可执行结论；已知停牌与未知状态不能合成一种「正常」状态 |
| 晚到/修订 | 保留已完成信号、快照与建议；后续开市日按各自 as_of 可见，不补跑过去信号消除缺口 |

## 7. 验收（测试名，待实现）

全部使用合成代码 A/B（含虚构 BJ 标的）与虚构日历日期 D0<D1<D2；需日期类型时由夹具构造，不能取真实交易日或样本。切换边界、跨年与时区场景也用合成映射。表中无测试代码，列名为 Given/When/Then；当前文档验收不等于下列测试已通过。

| 测试名 | Given | When | Then |
| --- | --- | --- | --- |
| `test_pn03_calendar_primary_index_diff` | 合成两段主源及有差异的指数集合 | 合并并核对 | 主源不被指数重定义；双向差异、覆盖差异与来源摘要可读，不报一致 |
| `test_pn03_calendar_overlap_mismatch` | 两段重叠日开市状态不同 | 校验候选 | 拒绝采用冲突结果，列差异，不静默择一 |
| `test_pn03_calendar_sha_mismatch` | 合成日历摘要与声明不符 | 核验 | 不播种、不报补齐 |
| `test_pn03_calendar_cross_year_and_holes` | 跨年覆盖含已知休市日，另组区间缺一天 | 播种合成业务日历并读时钟/窗口 | 开休市一致；缺日为 `calendar_not_covered` |
| `test_pn03_future_calendar_not_covered` | D2 超出主源覆盖 | 日历与快照调用 | 保留 `calendar_not_covered`，不按星期或指数推断 |
| `test_pn03_verification_not_business_calendar` | 验证消费者成功，业务日历缺日 | 读业务日历 | 仍报 `calendar_not_covered` |
| `test_pn03_suspended_day_is_trading_day` | D1 开市，A 明确停牌 | 日历与行情消费 | D1 仍交易日，A 停牌不作为有效交易 K、不出可执行结论 |
| `test_pn03_missing_row_not_suspension` | 通达信/HF 缺行，另组零成交有行 | 状态解释 | 缺行保持未知、不造占位；零成交不自动停牌 |
| `test_pn03_event_after_asof_excluded` | e≤D1，事件可见时刻晚于 D1 截止 | 对 D1、D2 分别派生并 prepare | D1 因子不含该事件，D2 满足可见条件才可用 |
| `test_pn03_event_without_available_at_is_gap` | 事件无可验证可见时点 | 因子适配到 prepare | 不作为已可见事件，不注入默认值，因子缺口可读 |
| `test_pn03_qfq_asof_anchor_equals_raw` | 合成有效因子、原价与带时区 as_of | 每个 T 独立 prepare，并用等价时区瞬时重放 | T 日 qfq 等于 raw，T 取北京日期，结果一致 |
| `test_pn03_latest_anchor_display_only` | 最新日锚序列与不同锚末值 | 请求信号/回测/指标；另请求展示 | 前三者拒绝误用；展示显式标注锚点，不污染信号 |
| `test_pn03_absolute_threshold_uses_raw` | raw 与展示 qfq 跨越夹具中的既有绝对价阈值 | 求值价格门禁 | 仅用 raw，不改阈值 |
| `test_pn03_bj_factor_missing_not_one` | 合成 BJ 原价存在，gbbq 无因子 | prepare | `adjust_factor_missing`，qfq 为空，不补 1 |
| `test_pn03_factor_revision_preserves_old_signal` | D1 信号完成后 D2 新因子版本可见 | D2 求值与 D1 重放 | D1 使用旧可见版本，旧信号指纹不变，不混快照 |
| `test_pn03_listing_unknown_not_executable` | 上市前无行情、上市状态时点未知 | 求值 | 不补行情，不据缺行判断可交易，缺口可见 |
| `test_pn03_zero_mairui_calls` | 本节全部离线用例 | socket 探针与外呼入口计数 | 麦蕊 0 次，不读真实库行 |

## 8. 未验证清单

| 项 | 默认边界 |
| --- | --- |
| 主源真实文件 sha、重叠一致性、指数差异及用户库覆盖 | 未验证；不以合成核验替代 T-B143w / S05 数据前置 |
| gbbq 连乘式、复杂权息真实性、历史事件版本完整性 | 未验证，算法默认不生效，C5 缺口照旧 |
| available_at 来源、registered_at 等价性、旧快照首次可见记录 | 未验证；无可验证时点不进入当时可见因子 |
| 上市/停复牌时点覆盖、北交所至少 20 只对算、history 分页上限 | 本单未验证；不补数据、不升级覆盖结论 |
| owned 快照携带因子的接线、冻结结构位 | 未验证/待实现，见 §11；不宣称已落地 |

无出处的参数、容差或阈值一律「未验证，默认不生效」。本单不新增策略参数。

## 9. 硬红线

真调麦蕊（含补取）、生产部署、删除用户数据、对外发送、解除 HALT、恢复出网、backfill --apply、通达信真实全量导入：**每项均需用户本人批准**。真实写库、真实条件替换、错后缀库存修正同样需用户本人批准。本契约不构成批准，不承接旧调用额度或自动恢复授权。实施与验收不得把真实行情或私有样本写入仓库或发给外部模型。

## 10. 实施单（建议占号，不建任务文件）

占用核对：团队 tasks 文件最大后端 T-B150、测试 T-T82；T-B148（ready）、T-B149（北交所路由）已有文件，T-B151 已归同源替换；plan-next §7 已占 T-B152–T-B161、T-A161–T-A167、T-T84/T-T85、T-R73–T-R75。团队测试状态确认 T-T83 已派 T-B149 路由失败测试，不再给 PN-06。新建议从 T-B162、T-T86 起；这些是建议占号，最终由编排者分配，不创建 `/workspace/team/tasks` 文件或仓库 tasks 文件。

| 建议号 | 范围 | 依赖 | 验收 | 硬红线 |
| --- | --- | --- | --- | --- |
| T-B162 | 权息可见性、available_at 字段或等价证据、prepare 输入路径与缺口、展示锚隔离；因子进入 owned 快照的接口归属见 Q5。冻结位保持已知问题 | 本契约合入；T-B143w 权息/日历数据前置；Q3/Q5 裁定；离线实现不依赖真调 | §7 权息/qfq、缺口与零外呼用例；不补 1 | 遵守 §9；真调/真写库等需用户本人批准 |
| T-B153（沿用，不新占） | S05：日历主源补齐、交易日判定、核对差异、`calendar_not_covered` | T-A153；本契约；矩阵表述同步（#136）；数据前置沿 T-B143w | §7 日历用例与 S05 覆盖/来源/未知未来验收信号 | 遵守 §9；本契约不批准播种用户库 |
| T-T86 | 只改 tests，PN-03 日历与权息验收，可按实现分批先红后绿 | 本契约合入；T-B153 / T-B162 分批交付 | §7 全部 `test_pn03_*`；不静默跳过或记通过 | 遵守 §9；纯合成、外呼 0、真实行 0 |

PN-06 的 T-B163、T-T87 见 [post-close-synthetic-loop.md](post-close-synthetic-loop.md) §10。若日历必须另拆实现单，下一候选为 T-B164，须重新核占并裁定后才占，本稿不新占该号。

## 11. 待裁定（每项附推荐）

| 项 | 推荐与未裁定边界 |
| --- | --- |
| Q1 T-A160 与 §7 S03 占位冲突 | 推荐以编排者本轮派单为准：T-A160 是旧 PR 收口及本次 PN-03/PN-06；S03 包络契约改建议下一空号 T-A168，后端仍沿用 T-B152，测试改建议 T-T88（T-T83 已占）。不改 §7 原表；S02/S06/PN-08/09 原引用 T-T83 的归属也由编排者整理，不能自动借用本单 T-T87 |
| Q2 PN-03 日历实施是否并入 S05 | 推荐沿用 T-B153，避免双单；T-A161 的日历契约占位建议由编排者确认改作本契约日历复核/同步范围，不自动释放或另派该号。若必须拆开，再核下一号 T-B164 |
| Q3 是否新增 available_at，还是以快照注册时刻推导 | 推荐显式保存事件版本 available_at 及快照证据：首次进入所用快照且可引用时刻，Asia/Shanghai，按瞬时与 as_of 比较。只有 registered_at 被证明具有此语义且不可回填改写时才允许等价推导；未知历史不可倒填。来源/定义未验证，裁定前无时点事件不得当作已可见 |
| Q4 合成源 source 取值 | 推荐沿用 fake，不新增枚举；当前 daily_bars CHECK 已允许 fake，已有测试也使用 fake。若实施发现其他所需字段约束不允许，再列具体冲突，不能伪装 mairui；与 PN-06 §11 Q2 同项 |
| Q5 正常 owned 路径尚无因子输入 | `build_owned_snapshot` 的 `_instrument` 未携带 factors，`analyze` 取 instrument 的 factors，缺省空列表。推荐 T-B162 接通受可见性约束的因子证据到不可变快照/等价输入，T-B163 复用；PN-06 不通过改写已存快照或伪造 prepare 返回值宣称全绿。具体接口与版本固化方案未验证，待裁定 |

日历主源、qfq 锚定、§14 就绪收紧、T-B151 同源替换归属、北交所单位前置及本人批准关口均已裁定，不在本节重开。

## 12. 受影响可执行入口与逐项验收

按 TEAM-RULES「11-15 01:05 治理升格」L-042/L-043 追加入口清单，不拆本契约、不重复正文。下列测试名均为待实现的离线验收，**全部未验证**，不代表本次运行通过；§7 的函数场景不能替代 CLI、probe、Windows 或 SQL 原入口验收。标为未验证的旁路亦不得据此宣称符合 PN-03。

统一输入 S 与 §7、PN-06 §7/§12 共用：虚构 A/B（含仅供离线解析的 920 前缀代码）、D0<D1<D2、跨年开休市及缺自然日两组日历、合成 OHLC、固定北京时钟、同一快照及早到/晚到/无 available_at 事件。JSON、ZIP、CSV、SQL stage 都从 S 派生；格式需要具体日期时只映射夹具日期，另以旧 Before 常量构造边界两侧，绝不取真实行情。所有写入仅限隔离临时存储；外呼和真实行访问为零。真调麦蕊、对真实库 --apply、通达信真实全量导入仍须用户本人批准，见 §9。

以下路径中的 `app/` 均指 `src/backend/app/`；同名函数按路径区分。表中验收名后缀对应下表完整测试名，不能以同一行之外的新入口结果代替。

| 类型 | 标识 | 与本契约的关系 | 验收后缀 / 状态 | 不得替代 |
| --- | --- | --- | --- | --- |
| 函数 | `app/aggregates/calendar.py` 的 `seed_calendar` | §2–§3 全自然日播种；当前可覆盖 is_open | `seed_calendar`；未验证 | 仅验证 JSON 合法 |
| 函数 | `app/aggregates/calendar.py` 的 `market_clock` | §3 北京日期、休市与缺覆盖 | `market_clock`；未验证 | 播种成功 |
| 函数 | `app/reports/service.py` 的 `covered` | §3 当日覆盖前置 | `covered`；未验证 | market_clock 用例 |
| 函数 | `app/marketdata/daily_snapshot.py` 的 `_sessions` | §3 窗口不能缺自然日 | `sessions`；未验证 | 当日 covered 用例 |
| 函数 | `app/marketdata/daily_snapshot.py` 的 `build_owned_snapshot` | §3、§4 日历及因子输入缺口 | `owned_snapshot`；未验证 | _sessions 单测 |
| 函数 | `app/features/pipeline.py` 的 `prepare` | §4 可见性、qfq@as_of、缺因子 | `prepare`；未验证 | 导入事件成功 |
| CLI | `python -m app.cli calendar-seed`（`app/cli/calendar_seed.py` 的 `main` 亦可直调） | 当前只读 `config/trading_calendar.json`；默认 dry-run，--apply 才写库，非完整 merged_calendar | `calendar_seed_cli`；未验证 | seed_calendar 单测、验证年历成功 |
| CLI | `python -m app.cli.tb143_export gbbq` | §4 导出事件快照；输出无 available_at | `gbbq_cli`；未验证 | 解码函数单测 |
| CLI | `python -m app.cli.tb143_export day` | §2–§3 日线核对输入；可传 --before，不定义日历 | `day_cli`；未验证 | 新日历合并测试 |
| SQL | `src/backend/probes/tb143_load_meta.sql` | §4 gbbq→market.ex_rights_events；当前 stage 无 available_at | `load_meta_sql`；未验证 | gbbq CLI 或 prepare 单测 |
| Windows | `src/backend/probes/tb143_day_load_runner.ps1` | 只导日线，不改日历；默认 Before 为 2023-11-13，仍是旧截止日入口（L-020/L-043） | `day_runner_ps1`；未验证 | PN-03/C1 取消截止日的新入口测试 |
| SQL | `src/backend/probes/tb143_load_day.sql` | 只导日线，不补日历；强制 trade_date 小于传入 before | `load_day_sql`；未验证 | PS1 调用成功、新 CLI 无截止日测试 |
| 研究脚本 | `docs/strategies/calendar/build_trading_calendar_2026.py` | 仅生成年份预公告文件，不能证明 C8 历史已补齐；本单不改/运行该目录 | `research_calendar`；未验证 | calendar-seed 验证成功 |
| probe | `src/backend/probes/tb143_pg_selfcheck.sh` | 自建临时 PG 并执行两份 SQL，含权息表；无业务日历/available_at 验收 | `pg_selfcheck`；未验证 | 旧自检 PASS、新函数测试 |
| HTTP | `GET /today`（`app/api/v1/aggregates.py` 的 `today`） | §3 market_clock 的接口传播 | `today_http`；未验证 | service.today 或 market_clock 单测 |
| HTTP | `GET /terminal`（`app/api/v1/aggregates.py` 的 `terminal`） | 同一业务时钟的另一路由 | `terminal_http`；未验证 | /today 路由测试 |
| HTTP | `GET /market/overview`（`app/api/v1/aggregates.py` 的 `overview`） | 同一业务时钟的市场读取 | `overview_http`；未验证 | /today 路由测试 |

| 测试名 | Given | When | Then |
| --- | --- | --- | --- |
| `test_pn03_entry_seed_calendar` | S 的已核对覆盖与冲突候选 | 经播种接线调用 seed_calendar | 覆盖内开休市齐全；冲突在写入前拒绝，不以函数可覆盖为授权 |
| `test_pn03_entry_market_clock` | S 的休市、缺日及等价时区瞬时 | 分组调用原函数 | 休市找前开市日；缺日/覆盖外报 calendar_not_covered，时区等价 |
| `test_pn03_entry_covered` | S 的开市、休市、未知日 | 分别调用 covered | 真、假及带 CALENDAR_NOT_COVERED issue 的错误三者区分 |
| `test_pn03_entry_sessions` | S 的完整/缺日窗口 | 调用 _sessions | 完整只取开市日；缺自然日返回缺覆盖，不按星期补 |
| `test_pn03_entry_owned_snapshot` | S 的窗口缺日或因子未接通 | 调用原快照及消费路径 | 保留日历/因子缺口，不改存档 JSON 制造成功 |
| `test_pn03_entry_prepare` | S 的可见、晚到、无时点因子及 BJ 无因子组 | 各 T 调用 prepare | 仅可见版本入选，T 锚等于 raw；缺因子为空并留 gap，不补 1 |
| `test_pn03_entry_calendar_seed_cli` | S 映射为仅 2026 预公告 JSON，另有 merged_calendar 冲突组 | 经命令分派和模块 main 分别 dry-run；隔离库验证 --apply 接线 | 默认零写入；单年校验不报 C8 补齐；冲突不得静默覆盖，缺守卫则验收失败并保持未验证 |
| `test_pn03_entry_gbbq_cli` | S 派生的合成事件包与匹配/不匹配摘要，解码依赖用合成替身 | 执行原 gbbq 子命令，不加载真实密钥 | 摘要错误拒绝；成功保留版本；无 available_at 仍不能进入可见因子 |
| `test_pn03_entry_day_cli` | S 派生 ZIP，日期跨旧截止边界 | 原 day 子命令分别不传/显式传 --before | 无参数不暗截；显式窗口与拒绝/跳过计数可审阅，不提升日历覆盖 |
| `test_pn03_entry_load_meta_sql` | S 派生 CSV、临时表及重复事件 | 在隔离 PG 执行原 SQL 后接可见性检查 | 版本可追溯且重复不增；stage 无时点只留缺口，registered_at 不自动冒充 available_at |
| `test_pn03_entry_day_runner_ps1` | S 的跨截止年度包与隔离命令替身 | 运行原 PS1 默认及显式 Before 两组 | 揭示默认 2023-11-13 及每次 SQL 参数；无声明截断即失败，不报 PN-03/C1 已取消截止日 |
| `test_pn03_entry_load_day_sql` | S 的 before 前、等于、晚于边界 CSV | 在隔离 PG 分组执行原 SQL | 旧边界拒绝整批且无静默丢行；窗口须显式声明，不报取消截止日通过，不写日历 |
| `test_pn03_entry_research_calendar` | S 的年份映射与历史缺口 | 在临时副本隔离执行原生成逻辑 | 单年输出不冒充 merged_calendar/C8；不得写回 docs/strategies 或业务库 |
| `test_pn03_entry_pg_selfcheck` | S 派生临时 PG 数据与同一事件版本 | 通过原自检入口执行并检查其覆盖范围 | SQL 证据可追溯；不因现有 PASS 宣称日历补齐或事件可见性已验收 |
| `test_pn03_entry_today_http` | S 的缺日/已知休市两组 | 本地请求 GET /today | 缺覆盖错误不吞成休市；已知休市沿原协议，无外呼 |
| `test_pn03_entry_terminal_http` | 同一 S | 本地请求 GET /terminal | 独立验证缺覆盖与休市传播，不借 /today 结果 |
| `test_pn03_entry_overview_http` | 同一 S | 本地请求 GET /market/overview | 独立验证缺覆盖与休市传播，不借 /today 结果 |

检索补列的间接日历消费者如下，**逐个未验证**，不能用上述直接入口用例宣称通过；后续均须以 S 单独记录原入口的缺覆盖/可见性结果。它们不因不在本单实现范围而被视为不存在。

| 类型 | 标识与关系 | 状态 / 不得替代 |
| --- | --- | --- |
| 函数/任务 | `app/marketdata/daily_bars.py` 的 `backfill_window_days`、`fetch_and_record`、`daily_bars_fetch_task`；`app/ingest/daily_bars_plan.py` 的 `window_days`、`ready_for_window`：取数窗口 | 各入口未验证；不得用 _sessions 单测替代 |
| CLI | `python -m app.cli daily-bars-backfill`、`python -m app.cli daily-bars-import-tdx` 及 `app/cli/tdx_import.py` 的 `recommended_until`：日历推导窗口 | 各入口未验证；不得用新 day CLI 测试替代 |
| 函数/任务 | `app/workers/daily.py` 的 `phase`；`app/workers/jobs.py` 的 `slot_jobs`；`app/signals/service.py` 的 `calendar_state`；`app/tracking/service.py` 的 `calendar`、`run_one`：阶段/到期日 | 各入口未验证；不得用 market_clock 单测替代 |
| 函数 | `app/marketdata/owned_daily_read.py` 的 `OwnedDailyBarsReader.read`；`app/api/v1/portfolio.py` 的 `previous_open_day`；`app/reports/comparison.py` 的 `apply`；`app/reports/dimensions.py` 的 `financial_pit`：价格/比较日/可见日 | 各入口未验证；不得用 prepare 单测替代 |
| 函数/HTTP | `app/marketdata/dataset_queries.py` 的 `validate_dataset_query`；`app/api/v1/security_fund_flows.py` 的 `validate_range`、`GET /securities/{code}/fund-flows`：覆盖校验 | 各入口未验证；不得用 /market/overview 测试替代 |
| 函数/任务 | `app/risk/rc1.py` 的 `load`、`assess`；`app/risk/worker.py` 的 `task`；`app/plans/worker.py` 的 `check`、`task`；`app/feedback/pause.py` 的 `apply_receipt`、`resume_due`：日历风控/恢复 | 各入口未验证；不得用 PN-06 风控新测试替代 |
| 函数/任务 | `app/intraday/engine.py` 的 `session`、`compute`；`app/importing/pipeline.py` 的 `_calendar`、`load_context`；`app/master/mairui_snapshot.py` 的 `apply_delivery`、`latest_visible_flags`：盘中/导入/主数据 | 各入口未验证，不接入本次离线成功声明；不得用盘后新测试替代 |
| 函数/任务 | `app/ingest/verify_licence.py` 的 `process_verify_intent`、`tick`：验证年历不写业务日历 | 各入口未验证且禁真调；不得用验证成功代替 C8 |
| probe | `src/backend/probes/tb81_evidence.py` 的 `analyze`；`src/backend/probes/p13_analyze.py` 的 `analyze`：单份日历/研究可见性 | 各入口未验证；旧固定窗口或研究日历结果不证明业务覆盖 |
