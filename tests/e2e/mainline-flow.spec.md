# G-STAGE8 主线 E2E 用例规格草稿

状态：DRAFT，供前端与测试按编号实现；本文件不是可运行的 Playwright 测试，未执行任何下列用例。
依据：当前 main `2051c8f23fed2428e32ae4bdd61636066b0c340f`，含 #301 merge `2051c8f` 的 PN06 日历行隔离修复。只描述现行契约与现有测试入口，不修改契约、建议引擎、风控、日历或数据接线。
目标：用户从真实登录进入本人账户，上传纯合成文件、预览并确认，重读持仓与导入记录，再查看本人日报和今日关注；每一环均有服务端结果与页面对应证据。

## 0. 当前主线前置核验

#301 只改 `tests/backend/unit/test_pn06_entry_wiring.py`，未改生产运行路径。完整主线 E2E 启动前，先在独占测试库执行既有 `test_pn06_calendar_isolation_preserves_preexisting_and_cleans_exception`，确认本轮新增日历行在正常退出和异常退出后均被清理，预存日历行保持原值；该项是资源隔离前置，不计浏览器 E2E 通过。缺少独占 PG、网络隔离或清理回证时标记 `blocked`。

## 1. 执行模式与资源前提

| 模式 | 允许执行 | 不得据此声称 |
|---|---|---|
| `isolated-synthetic`（本清单的完整验收模式） | 后续实现任务启动的独占测试 API/worker/PG/Redis/加密临时存储，全部合成账户、文件与行情；前端正式构建关闭 MSW；浏览器用真实登录表单与真实 API | 生产数据可用、真实交易收益、日历或 provider 已验证、部署验收 |
| `existing-stack-readonly`（另行获派后） | 运维指定的现栈地址与版本、已批准会话下仅导航和 GET，对空态/缺口/已有可见数据取证 | 登录、上传/确认/生成日报、幂等写入或跨用户隔离已覆盖；不得将合成成功数并入此模式 |

本 PR 只交规格，未启动上述任何资源。后续实现须单独登记唯一作者与资源归属，不改现有 CI 选择集或已有测试。
完整验收前固定 `api_sha`、`frontend_sha`、部署/测试模式、独占资源标识、`run_id`、浏览器版本与日历覆盖；缺少任一必要资源报 `blocked`，不跳过后算全绿。
测试上下文的 `source=fake` 仅作合成来源标识，不登记为正式 provider；批准测试用户由独占夹具建立，不走生产审核、不触发 G7。
隔离服务必须为 `MAIRUI_MODE=replay`，用测试配置启动，不读取生产 env 或证书；浏览器上下文全新、禁持久 profile/Service Worker/外站请求；API/worker 同样禁止真实麦蕊及其他出网。允许的本地 API/资源地址须显式列出，不能只管浏览器出网。
桌面使用既有 1440×900、dark、zh-CN、Asia/Shanghai；证据汇报时间另记 America/Denver（MST），数据时点保留原偏移。

## 2. 合成夹具与预期账本

| 夹具 | 必要属性 | 验证用途 |
|---|---|---|
| 用户 A、用户 B | 两个 approved 合成用户，数据互不重合；密码仅内存生成，不入源码、控制台、截图、trace 或 HAR；另有一个 pending 用户 | 真登录、缓存清理、跨用户隔离、未批准拒绝 |
| A 的账户 A1/A2 与 B 的账户 B1 | A1 创建早于 A2；A1 与 A2 的证券及数量不同；B1 只归 B | 明确默认账户与合并范围，外来 account_id 不可穿透 |
| 导入文件 T/P | 内存或独占临时目录生成的通达信 trades/positions CSV；只含虚构数据、固定合成证券，禁止真实资金账号与股东代码 | 走真实解析器；文件 hash、行数与金额用 Decimal 预注册；P 显式 snapshot_as_of |
| 日期 D/D2 | 已覆盖的合成开市日及下一日；API/worker 时钟同源，阶段不依赖机器当前北京时间 | 解析、T+1、today 默认日期和日报选择稳定 |
| 日报 R(D) | 测试服务用冻结的合成输入生成完成版本；保存 revision、账户、数据时点、非空 stocks 与至少一条可解析引用 | 真实读取投影；不是浏览器拦截后塞响应，也不强求真实策略产生建议 |
| 对照状态 | 无账户、账户空持仓、从未有行情、无完成日报、partial 完成版、新版 building、有无 warnings/error 的独立批次 | 空态、缺口、状态与错误分离；互不复用已改变的批次 |

T 与 P 在不同测试账户/独立 case 中跑，不能把同一持仓既从成交重建又叠加快照来凑预期。
账本记录输入字节 SHA256、规范化行、written 计数及确认前后资源计数；预期不得由被测 HTTP 返回值自己复制生成。
日报是不可变快照：导入后不要求旧日报自动更新。先完成导入与持仓重读，再由独占任务生成新完成日报或选用同输入版本，记录两者边界。
`/portfolio` 不传 account_id 为本人账户合并；`/today` 默认账户按契约为最早未归档账户，不能拿两者总额直接要求相等。

## 3. 主线用例矩阵（全部待实现）

前端负责浏览器动作与展示断言，测试负责独占夹具、真实 API/worker 侧账本与权限验证；每项均需二者对齐后记录结果。
`UI+API` 指观测真实网络响应后断言 DOM 与预注册账本；不能仅断言响应 200、页面存在或从响应构造相同预期。

| ID | 入口与前提 | 用户动作 / API 检查 | 必须满足的断言与证据 |
|---|---|---|---|
| ML-00 | 独占测试库，当前 main 含 #301 | 先执行既有 PN06 日历隔离测试，再检查清理回证 | 预存日历行值不变；正常与异常退出新增行均清除；缺 PG、隔离或回证为 `blocked`，不计浏览器 E2E 通过 |
| ML-01 | 无会话，受保护 `/portfolio` | 直接打开，再检查 `/api/v1/portfolio` | API `401 AUTH_REQUIRED`，页面进入登录；无持仓内容闪现；仅记录路径/状态，不记录 cookie |
| ML-02 | 用户 A，真实 `/login` | 填用户名/内存密码并提交；观测 `POST /api/v1/auth/login` | `200`；后续本人身份/账户读取正确；`next=/portfolio` 合法内站回跳，直接 `/` 落 `/today`；不以注入 cookie 代替此步骤 |
| ML-03 | 单独错误密码与 pending 用户 | 各执行一次登录 | 错密码 `401 INVALID_CREDENTIALS` 及 `login-error`；pending `403 ACCOUNT_NOT_APPROVED`、进入账户状态页且无业务会话；不触发真实账户锁定 |
| ML-04 | 用户 A、A1/A2 已存在 | 打开 `/portfolio`，选择 A1 再 A2 | `account-select`、`positions-tab` 与相应 account_id 请求一致；两者数量/名称来自各自账本，不混行 |
| ML-05 | A1、无未决批次 | 点击 `go-import` | 进入 `/portfolio/import?account_id=A1`；`import-upload` 可见，账户正确；未选文件类型/文件时 `upload-submit` 不可提交，无上传请求 |
| ML-06 | A1，文件 T；P 在独立账户重复 | 选 trades 或 positions，上传文件；P 显式快照时间 | `POST /imports` 为 `201` 且取得真实 batch_id；轮询从 uploaded/parsing 至 previewed，间隔不得小于1秒；超时记录最后状态为失败/阻断，不用固定 sleep 掩盖 |
| ML-07 | previewed 批次 | 检查 `/imports/{id}` 与 `/rows`、页面 `import-stats`/`rows-table` | 行数、种类、规范化字段和提示匹配输入账本；只展示 raw_masked；未确认前 `/trades` 和持仓数量不因预览改变 |
| ML-08 | 带 warning/needs_action 的独立合成批次 | 不确认提示尝试提交，再按 resolution_choices 处理并确认 warning | 服务端对应 `422 IMPORT_WARNINGS_UNACKNOWLEDGED` 或未决提示拒绝；UI不得显示完成；处理后提交请求体正确，覆盖原因必填，不伪造绕过选项 |
| ML-09 | 可提交且无 error 行的 T/P | 点击 `confirm-import`，观测 `/imports/{id}/confirm` | `200 status=committed`；written.trades/events/snapshot_positions 与该夹具账本一致；`import-done` 与批次 GET 同为 committed，失败请求绝不显示成功 |
| ML-10 | ML-09 的同用户/批次/请求体/key | 在隔离 API 下重发同一确认；另以同 key 改请求体 | 同请求只写一次，响应相同且 DB/导入列表无重复；变请求体 `409 IDEMPOTENCY_CONFLICT`；key 不打印；不把“重复上传有 warning”误认成确认幂等 |
| ML-11 | 确认后的本人批次 | 导航回 `/portfolio?tab=imports&account_id=A1`，再进持仓，reload | 导入记录按真实 batch_id/committed 可见；T 的成交计数/数量及 P 的快照持仓符合各自账本；硬刷新后仍可见，证明不是组件临时 result 对象 |
| ML-12 | 正常持仓与缺行情夹具分别执行 | 查看数量/可卖/成本/估算提示 | 数值按 Decimal 账本核对；缺价格时 `estimated=true`、市值/盈亏 null 显示“—”和估算，`data_status/gaps` 原样可解释；不得填假价/0 或将未知当正常 |
| ML-13 | 无账户、空持仓、解析错误批次分别执行 | 打开持仓/导入，上传类型不符或含行 error 的文件 | 无账户导入入口不可用；空持仓有“暂无持仓”；文件级 `422 IMPORT_FILE_ERRORS` 不创建批次；mode=all 行错 `422 IMPORT_ROW_ERRORS` 不写数据；这些空态不冒充500错误 |
| ML-14 | 本人 R(D) 已完成、D2 无完成版 | 打开 `/daily-reports`、`/daily-reports/D`、D2 | 列表选最新完成日期；`daily-report`、日期和 `report-account` 匹配 R(D)；D2 API `404 NOT_FOUND` 不伪造日报；列表无完成版显示“暂无日报” |
| ML-15 | R(D) 非空且至少一条引用 | 查看股票卡与引用，记录同日期重复 GET | `stc-{code}`、金额/数据时点与快照一致；evidence_ids 在同份 evidence 中可解析、锚点可到达；重复读取不改写快照，证据缺失不能填事实 |
| ML-16 | partial 完成版＋同日新版 building | 浏览 D 详情与 `/today` 的日报状态 | 旧完成版仍可读；partial 在 today 映射 ready，但 `report-gaps`/对应缺口仍可见；`data_as_of` 按组件最早非空值，不拿 generated_at 补缺 |
| ML-17 | today 的 ready / generating / not_yet 分别执行 | 打开 `/today`、点击已生成日报链接 | `today-page`/`today-daily-report` 状态与真实 `/today` 相同；仅 ready 自动取详情且跳正确日期；其他两态无假“已生成”和反复请求不存在详情 |
| ML-18 | A1/A2 持仓、一个额外重点关注证券 | 查看 `today-focus`、默认对账、免责提示 | focus 与本人持仓∪重点关注及契约排序/截断一致；不以“没有建议”删持仓；对账按默认账户，与同账户端点比对；缺源不渲染为有信号或新鲜行情 |
| ML-19 | A 登出后同一浏览器以 B 登录 | 先打开 A 页，再登出与登录 B，重读三个页面 | B 页面无 A 的批次、持仓、日报或 focus；新用户请求/ETag 不沿用 A 的结果；验证 accountQueries 的 clearEtagCache/qc.clear，不能只用独立新context替代缓存切换 |
| ML-20 | 独立 B 上下文、A 的已知合成 ID | GET A 账户 portfolio/import列表，GET批次/rows/errors.csv，确认 A 批次；再读 A 独有日期日报 | 账户/批次相关请求与日报均 `404`，无跨用户写入/导出；确认请求带 B 有效CSRF以防403掩盖归属问题；today只含B，不要求不存在的“按用户查日报”端点 |
| ML-21 | 无会话 / 缺CSRF / 正确CSRF 三组 | 对导入写入口用同一个合成文件构造请求 | 无会话 `401 AUTH_REQUIRED`；已登录缺/错CSRF `403 CSRF_FAILED`；正确会话才进入业务校验；Origin/参数变体按现行规则，不扩大白名单 |
| ML-22 | 独占测试服务可控500、已建立today缓存 | 首次请求失败、已成功后刷新失败各执行一次 | 首次ErrorBox不是“暂无”；刷新失败保留已读数据并有 `today-refresh-error`；不能吞500成空成功；失败注入只能用于负例，不据替换响应声称完整链通过 |

主成功链为 ML-01/02 → ML-04至07 → ML-09/11/12 → ML-14/15/17/18；其余为独立边界/负例，报告逐个计数，不只报一条“全链通过”。
必要负例 ML-19/20/21 是验收项，成功链通过不能豁免它们；304 需要同用户同范围已有成功响应，无缓存的304不可单独当数据读取成功。

## 4. 入口与断言来源（路径相对本文件）

| 来源 | 适用内容 |
|---|---|
| [api-contract §1.3/§7.1/§7.2/§7.3/§7.8](../../docs/api-contract.md) | 认证/CSRF、账户归属、导入两步与幂等、持仓估值、默认账户、today和日报完成版 |
| [routes](../../src/frontend/src/app/routes.tsx) | 页面路径；日报旧 `/reports` 只重定向，不新增 `/reports/daily` |
| [LoginPage](../../src/frontend/src/pages/auth/LoginPage.tsx) / [accountQueries](../../src/frontend/src/api/accountQueries.ts) | 表单真实登录、登录/登出清缓存、解析轮询、确认key生命周期 |
| [PortfolioPage](../../src/frontend/src/pages/portfolio/PortfolioPage.tsx) / [ImportWizardPage](../../src/frontend/src/pages/portfolio/ImportWizardPage.tsx) | account-select/positions-tab/import-* 与确认页面；选择器以当前页面角色和已存在 testId 为准 |
| [TodayPage](../../src/frontend/src/pages/today/TodayPage.tsx) / [DailyReportPage](../../src/frontend/src/pages/DailyReportPage.tsx) | today-* / daily-report / report-account / report-gaps / stc-*；不在本草稿强加新选择器 |
| [imports API](../../src/backend/app/api/v1/imports.py) / [daily_reports API](../../src/backend/app/api/v1/daily_reports.py) / [auth API](../../src/backend/app/api/v1/auth.py) | 真归属检查、确认幂等与审计、完成版投影、会话生成 |
| [既有 E2E 配置](playwright.config.ts) / [app 冒烟](app.spec.ts) / [p2n10](p2n10-mainline.spec.ts) | app目前只冒烟；p2n10为日报→风控→模拟链，不能替代本登录/导入链；本单不执行或改写它们 |

## 5. 实现交接与结果格式

1. **测试先准备**：按run独占数据和关闭出网；固定时钟/日历、两个用户三个账户、T/P文件及预注册账本、真实解析worker与日报生成入口。夹具准备失败报 blocked；不把准备脚本当端到端成功。
2. **前端再接动作**：真实登录、页面导航、上传/提示/确认；用已存在的getByRole/getByLabel/testId，避免nth或硬等。对关键响应先挂监听再点击，读完状态后做字段与DOM断言。
3. **测试补负例**：归属、CSRF、同key重放、金额/计数、快照不回写及无网校验；浏览器拦截只阻断出网或制造明确标记的失败，成功链禁route.fulfill/MSW/响应替换。
4. **接入规则**：未来实现使用明确的主线测试文件/配置，显式选择本套件；完整运行缺前提必须失败或blocked，不在缺环境时全部skip后exit0。保留既有测试和超时，不在本规格PR更改工作流、安装依赖、启动服务器或切换现栈。
5. **交付记录**：每个ID的pass/fail/blocked/not_run、真实采样时间MST、应用/API/前端SHA、run/job URL、请求路径/方法/状态、输入hash/预期与实际计数、截图与脱敏断言摘要；仅执行的ID计入通过，collection与规格审核不算E2E通过。
6. **隐私与清理**：登录步骤关闭录屏/trace；HAR禁保存，运行日志不含请求体、headers、cookie、CSRF或密码；公开截图只含合成数据。结束核自有资源身份后清理自有测试资源，保留归属与清理回执，不碰用户数据或其他任务资源。

验收入口：先由非作者评审本清单与现行契约一致，再由编排者分别派前端/测试实现；真正执行结果另报。契约/实现差异写入关联PR交Grok裁定，不在spec中新增语义。
DeepSeek：未用，原因：主线规格取证与评审不外包。
