结论：四功能尚未满足“每天能用”放行条件，本地栈大同步暂不放行；主线缺口、待批 PR 和未验证口径须按本清单闭合。

# T-A220「每天能用」里程碑验收清单

范围是实时行情、市场概览、禁投冷静期（restrictions）、复盘页（reviews）。引用的 PR 哈希是只读评审依据，不能替代合入主线后的验收。

## 一、实时行情

| 端到端看得见判据（一行一条） | 出处与当前状态 |
|---|---|
| 页面 `/terminal` 能加载终端表格，行情行有价格、涨跌、成交额、行情时间和盘中/收盘口径标签。 | 页面路由现有；目标读链见 `docs/contracts/T-A209-market-wiring.md` §0.3、§0.4；实时优先读链仍缺后端单。 |
| `GET /quotes?codes=` 返回本人证书范围内的行情，`GET /terminal` 与 `/today` 行复用同一来源，`GET /stream` 的 `quote` 事件只推送自选/持仓且带非空 `data_as_of`。 | API §7.3、§8；#347@e8771158（U1/U4/U8 口径文档）及 T-B195；主线仅有旧日线回退，未实现实时优先。 |
| 数据来源可追溯到本人证书、行情 `t`、`fetched_at`、批次和来源，证书之间不串读；`quotes_snapshot` 旧无归属行不得冒领。 | T-A209 §0.1–0.3、§0.4；#347@e8771158；T-O123 G1/G4 记为缺口。 |
| 无实时批次时显示本人可见的旧收盘并标 `stale`，无合格缓存显示 `unavailable`、字段 `null` 和 gap；证书失效时不显示旧价、不入队、不借他人证书。 | API §1.1、§7.3 的 T-A173/T-A193；T-A209 §0.3；应由后端和前端联调验证。 |
| 15:00 前后不把盘中行改成收盘，17:10 前不把日线当最终收盘；未来 `fetched_at`、停牌、缺量额、断点分钟线均保留缺口。 | T-A219 §4、`docs/contracts/daily-bars-source.md` §10；T-B195 U8；远程夹具必须覆盖边界。 |
| 量、额单位和累计/单根语义未证实前不转换、不补零；`tv` 不映射为规范化 volume，`ssjy_more` 的 `dm` 只按请求代码集回挂。 | #347@e8771158、`docs/contracts/T-B195-intraday-field-evidence.md` U8；参数保持关闭/null。 |

仍缺的单与负责角色：

- 后端：盘中采集、来源/证书隔离迁移、实时优先 `read_quotes`、交易时段调度和 signal-rt 接线，T-O123 G1–G4；单号待编排者分派。
- 前端：终端/今日行的 null、stale、basis 和断线轮询验收；单号待编排者分派。
- 运维：新鲜度/队列健康检查和资源实测，T-O123 G4/G6；不得打开 live。
- 研究员：U1/U4/U8 的供应商字段、单位、覆盖与涨跌停证据；未验证前保持关闭。
- 测试：用 mock 栈完成双证书、15:00/17:10、未来 `fetched_at`、缺量额和 SSE 断线矩阵。

## 二、市场概览

| 端到端看得见判据（一行一条） | 出处与当前状态 |
|---|---|
| 页面 `/market` 与 `/market/overview` 显示指数卡、涨跌分布、两市成交额、市场状态/参考区间和板块资金，并展示 `data_status`、`data_as_of`、gaps。 | #359@4ceaea33 的 T-A219 §1、§6、§8、§9；#280@28266492 已闭合三处前端差异；主线页面存在但后端尚未接线。 |
| `GET /market/overview` 返回 `MarketOverview`，指数来自同一可见批次，宽度按合格沪深股票同批聚合，`MarketBasis` 记录观察日、模式、范围和证据计数。 | #359@4ceaea33 §1–§3；主线 `aggregates.service.market` 仍固定 `unavailable/no_source`，缺后端实现单。 |
| 盘中来源为本人证书的 `quotes_snapshot`，收盘来源为 `daily_bars` 的 `source=mairui`、`adj_type=none`、本人证书且满足 17:10；不跨日拼接。 | #359@4ceaea33 §2、§4；T-A219 报告；真实来源操作须用户批准。 |
| 宽度排除停牌、零量、退市、ETF、指数和默认 BJ；涨跌停字段只有来源或 PIT 规则齐全时出现，否则 `limit_counts.enabled=false`、计数 `null`、`market.breadth.limit_counts/no_source`。 | #359@4ceaea33 §3、§5；#280@28266492 前端 null 展示已闭合。 |
| F25/G-02 regime、参考仓位区间、覆盖率阈值没有批准参数时保持 `null + market.regime/no_source`，不以样本或默认值补齐。 | #359@4ceaea33 §3.1、§7；T-A219 报告；研究员参数单缺失。 |
| 无证书、非交易日、开盘前、全空或部分缺失均为 HTTP 200 的可解释空态，保留可识别的指数卡片，不把样本和冒充全市场合计。 | #359@4ceaea33 §6、§8、§9；前端夹具由 #280@28266492 提供，后端入口未验证。 |
| 板块资金沿 `GET /market/sector-flows` 盘后来源展示；d 日资金流最早可见时点为下一交易日 09:30 与 `fetched_at` 较晚者，未满足时保持空集和 gap。 | API §7.3；#352@f95bb0b6（F21 PIT）；测试需用虚构资金流夹具。 |

仍缺的单与负责角色：

- 后端：实现 `market()`、快照来源/证书字段迁移、资格池/Decimal 聚合、PIT 和 gap 投影；缺单，后端负责。
- 前端：#280@28266492 的三处已闭合，仍需合入目标栈并对真实 API 做页面回归；若路由联调失败，前端负责，单号待编排者分派。
- 研究员：F25/G-02、U1/U4、涨跌停和覆盖率参数；未验证项不得启用。
- 测试：覆盖盘中/收盘、15:00/17:10、空证书、BJ 20 码门闩和 sector-flow PIT；单号待编排者分派。
- 编排者：#359 代码治理员审查完成后才可纳入同步窗口。

## 三、禁投冷静期（restrictions）

| 端到端看得见判据（一行一条） | 出处与当前状态 |
|---|---|
| 页面 `/restrictions` 能列出本人 active/expired 限制，支持按 kind、target_type、游标筛选，目标不可见不泄露存在性。 | API §7.5；#330@df368328、#341@e8b33edc、#348@4826e0c3 后端目标；当前主线仍是前端占位页。 |
| `GET /restrictions` 返回 `{items,next_cursor,gaps}`，`POST /restrictions` 支持 blocklist/cooling_off/mute 和本人幂等，目标名称缺失为 `name=null + no_source`。 | API §7.5；#330@df368328；#330 已批，需在目标主线注册路由后复验。 |
| `DELETE /restrictions/{id}` 首次与重复删除均返回原 `removed_at`、`status=removed` 和 `recheck`，只解除本次确实释放的原因，仍被其他限制覆盖的原因保留 active。 | API §7.5 §9；#341@e8b33edc（重复 DELETE）和 #348@4826e0c3（removed_at 过滤）阻断已闭合待批。 |
| 候选命中按 `[created_at, removed_at)` 与候选 `content.created_at` 的 PIT 比较，`until` 不得用当前时钟改写历史；重查证据不足时返回 gap，不以空数组冒充完成。 | API §7.5；`docs/contracts/T-A209-market-wiring.md` §4；后端合入后需远程回放验证。 |
| 空列表为 `200 items=[]`，过期行仍可见于按契约允许的投影，删除后候选/`today`/释放原因联动只显示真实释放事件。 | API §7.5 §9；T-A209 §4；联动入口尚缺统一 E2E 单。 |

仍缺的单与负责角色：

- 后端：#330 已批；#341/#348 阻断闭合但待批准、合入并注册路由，负责角色为后端/编排者。
- 前端：实现 `/restrictions` 页面、创建/删除/重复删除和 gap 展示；当前是占位页，缺单待编排者分派。
- 测试：隔离库虚构目标和候选，覆盖跨用户 404、冷静期边界、重叠限制、重复 DELETE；缺单待编排者分派。
- 运维：本功能无真实行情依赖，沿本地栈健康检查即可，不执行外部调用。

## 四、复盘页（reviews）

| 端到端看得见判据（一行一条） | 出处与当前状态 |
|---|---|
| 页面 `/reviews` 展示本人复盘列表、区间、当前版本、状态/时点和缺口，详情页可查看版本、时间线、证据与复盘笔记。 | API §7.8；#333@a1b7c3a8 前端类型/页面跟进；当前主线 `/reviews` 仍为占位页。 |
| `GET /reviews`、`GET /reviews/{id}`、`GET /reviews/{id}/versions`、`GET /reviews/{id}/versions/{n}` 均按本人隔离，资源/版本不存在或他人资源统一 404。 | #349@2fd6730c §7.8.1；#346@a501992d、#356@eccb3d25、#362@f27fba0f 后端实现链，须一起合入。 |
| `POST /reviews` 和版本保存使用完整整体替换体、空数组可清空、幂等键和 `base_version_no` 乐观并发，响应可解析 `Evidence` 和 timeline。 | #349@2fd6730c §7.8.1；#346@a501992d 已闭合整体替换，合入状态受 CI coverage 阻断。 |
| 四项结果指标 `holding_return`、`benchmark_return`、`excess_return`、`max_drawdown` 在口径未定稿时均为 `value=null`，`n` 保留真实样本数，顶层 gap 为 `outcome_metrics.<name>/no_source`。 | #349@2fd6730c §7.8.4；R332-benchmark；#362@f27fba0f 新增阻断②，#356+#362 必须一起合入。 |
| 成交、价格、基准和证据按知识时点过滤，`available_at`/导入时点晚于 `calculation_as_of` 的成交不计入；证据字段齐全且历史版本可追溯。 | R356-review（复审结论）；#362@f27fba0f；测试需验证前视排除。 |
| 无当前版本的旧复盘显示 `current_version_no= null`、详情 `current_version=null`，禁止保存；未知 timeline/gap 字符串显示“未知”而不转成零值。 | #349@2fd6730c §7.8.1、#333@a1b7c3a8；前端页面合入后需真实 API 回归。 |
| 无成交、无来源、结果期未结束分别显示 `user_input_missing`、`no_source`、`pending/not_yet_published`，不把未知指标显示为 0。 | API §7.8.1、§7.8.4；R346-review、R356-review。 |

仍缺的单与负责角色：

- 后端：#346@a501992d CI coverage 仍红；#356@eccb3d25 与 #362@f27fba0f 的阻断②须一起修复并合入，负责后端与测试。
- 前端：#333@a1b7c3a8 页面/类型需从占位路由接入并对接四个端点，负责前端；缺少的联调单待编排者分派。
- 测试：补“完整来源仍四项 null”、前视成交排除、Evidence 全字段、跨用户隔离和版本冲突入口断言，负责测试。
- 研究员：完成 §7.8.4 四项指标正式口径前，不得开启指标值；单号待编排者分派。

## 五、远程可测步骤（团队执行，全部使用虚构夹具或 mock 栈）

1. 启动隔离 mock 栈，确认网络拦截、虚构代码/UUID、无环境文件读取；运行前端路由 smoke，访问 `/terminal`、`/market`、`/restrictions`、`/reviews`。
2. 用 mock `GET /quotes`、`GET /terminal`、`GET /stream` 回放实时完整、stale、证书不可用、未来 `fetched_at`、缺量额和断线重连，断言不入队、不外呼、来源和时点不混。
3. 用市场概览虚构夹具回放盘中、收盘、15:00/17:10、空证书、非交易日、涨跌停无证、BJ 不足 20/足 20 双源，断言 `null+gap` 和 `data_status`。
4. 用隔离库调用 restrictions 的 GET/POST/DELETE，覆盖目标 404、cooling_off `until` 边界、重叠限制和重复 DELETE，核对 `recheck` 与状态事件。
5. 用隔离库调用 reviews 列表、详情、创建、版本和时间线，覆盖无当前版本、空数组清空、幂等冲突、前视成交、Evidence 字段和四指标 null 门控。
6. 运行对应后端单测、前端页面测试、契约检查和 secret scan，确认只含虚构数据；不把模型单测替代 HTTP 页面入口断言。

## 六、需用户本人确认（与团队步骤分开）

- 界面观感：本人查看四页在真实浏览器中的布局、空态文案、stale/partial/unavailable 标签和图表可读性。
- 真实数据操作：本人确认是否进行真实证书行情验证、真实持仓导入或其他生产数据操作；真调麦蕊、切 live 按团队红线审批（编排者可代批）；导入真实持仓、删除用户数据须用户本人批准；未获批前团队不得执行。

## 七、未验证参数清单（全部保持 enabled=false 或 null+gap）

| 参数/事实 | 保持方式 | 出处 |
|---|---|---|
| U1 全市场/指数实时字段、覆盖与统一批次 | `indices` 缺证为 null，`market.indices.<code>/no_source` | #347@e8771158、T-A209 U1 |
| U4 涨跌停来源、板块规则、最小价位单位 | `limit_counts.enabled=false`，计数 null，`market.breadth.limit_counts/no_source` | #359@4ceaea33 §5、T-A219 U4 |
| U8 `tv` 语义、Q1/Q2 量额单位、累计重置、竞价/停牌/ETF 覆盖 | 不映射、不补零，字段 null，`no_source` | #347@e8771158、T-B195 U8 |
| `quotes_snapshot` 来源/证书/量额/停牌列及证书隔离主键 | 旧无归属行不读，行情项 unavailable/null+gap | #359@4ceaea33 §2、T-O123 G1 |
| F25/G-02 regime 窗口、阈值、防抖、参考区间 | `regime=null`、`regime_position_range=null`、`market.regime/no_source` | #359@4ceaea33 §7、T-A219 |
| BJ 双源同日 20 码门闩 | 默认拦截，未满足不进入 scope、宽度和成交额 | #359@4ceaea33 §3.2、`daily-bars-source.md` §10（待合入） |
| F21 资金流 d 日首次可见时点与修订关系 | 未满足 PIT 时 `items=[]` 或字段 null+`no_source` | #352@f95bb0b6、API §7.3 |
| 复盘四项指标正式口径 | 四项 `value=null`，各顶层 `outcome_metrics.<name>/no_source`，`n` 照实 | #349@2fd6730c §7.8.4、R332-benchmark、#362@f27fba0f |

## 八、本地栈大同步可放行

- [ ] #359 代码治理员审查完成，#280 前端三处闭合内容已合入目标提交。
- [ ] #330 已批内容、#341/#348/#335 阻断闭合内容均完成批准、合入和 CI 绿。
- [ ] #346 coverage ratchet 变红已修复并全绿；#356 与 #362 作为一组合入，四指标仍有 null 门控和 no_source gap。
- [ ] 后端 `market()` 不再固定 unavailable；restrictions/reviews 路由已注册；实时读链默认离线且未打开 live。
- [ ] 四页及 `/quotes`、`/terminal`、`/stream`、`/market/overview`、`/restrictions`、`/reviews` 的 mock HTTP/E2E 和空态矩阵通过。
- [ ] PIT、证书隔离、15:00/17:10、BJ 默认拦截、Decimal 单位和前视排除均有可复现夹具证据。
- [ ] 未验证参数仍按第七节关闭；没有真实交易数据、证书、个人信息或私有样本进入仓库和产物。
- [ ] 团队步骤未真调麦蕊、未导入真实持仓、未解除 HALT；任何真实操作均已按红线取得批准（真调麦蕊可由编排者代批，用户数据操作须用户本人）并单独记录。
- [ ] `git diff --check`、契约检查、后端/前端目标测试和 secret scan 全部通过。
