结论：四项功能尚未满足“每天可用”放行条件，本地栈大同步暂不放行。判据只采用 `origin/main` 已合入的 `docs/api-contract.md`、`docs/contracts/` 文件和主线测试；未合入内容只列为待定。

# T-A220「每天可用」里程碑验收清单

范围为实时行情、市场概览、禁投冷静期（restrictions）和复盘页（reviews）。

## 一、实时行情

| 场景 | 主线基线与状态 |
|---|---|
| `/terminal` 页面展示价格、涨跌、成交额、行情时间及盘中/收盘口径 | 页面路由存在；实时优先读链仍缺后端单，待 API 与页面联调。 |
| `GET /quotes?codes=`、`GET /terminal`、`GET /today`、`GET /stream` | 以 `docs/api-contract.md` §7.3、§8 为基线；#347 仅为候选依据，未合入，不作判据。 |
| 证书、`t`、`fetched_at`、批次和来源可追溯且不串证书 | `docs/contracts/T-A209-market-wiring.md` §0.1–§0.4 为待验证缺口；无主线入口测试。 |
| 无实时批次显示 `stale`，无合格缓存显示 `unavailable`、字段 `null` 和 gap，证书失效不显示旧价、不入队 | 依 `docs/api-contract.md` §1.1、§7.3 的已合入结构，行为测试待新增，未验证。 |
| 15:00、17:10、未来 `fetched_at`、停牌、缺量额、断线均不改变收盘口径 | `docs/contracts/daily-bars-source.md` §10 和 `T-B195` 仅作主线规则依据；边界矩阵测试待新增，未验证。 |
| 量额单位、累计语义及 `tv` 未证实前保持关闭或 `null` | #347 仅为候选依据，未合入，不作判据。 |

## 二、市场概览

| 场景 | 判据与状态 |
|---|---|
| 页面 `/market`、`/market/overview` 与 `GET /market/overview` | 已批准基线为主线 `docs/api-contract.md` §7.3 的最小结构。响应 JSON 必须有 `trade_date`、`session`、`indices[]`、`breadth`、`regime`、`regime_position_range`、`turnover_total`、`data_status`、`data_as_of`、`gaps` 和现有 `basis` 字段。 |
| 新增字段、空态、批次键和 `MarketBasis` 计数口径 | 待定：待 #359（T-A219 契约，现 @f350a3ba，已按 T-G16 B1–B3 修订）合入。#280 草案及其夹具不作判据。 |
| 盘中/收盘来源、本人证书、17:10、BJ 门闩、涨跌停和 regime | 均待 #359 合入后再验收。#352 仅为候选依据，未合入，不作判据。 |
| `GET /market/sector-flows` 的 PIT | 主线 API §7.3 只作为路径基线；F21 的 #352 仅为候选依据，未合入，不作判据。 |

## 三、禁投冷静期（restrictions）

| 场景 | 主线基线与状态 |
|---|---|
| 页面 `/restrictions` 及 `GET /restrictions` | 依 `docs/api-contract.md` §7.5，列表返回 `{items,next_cursor,gaps}`，只读本人资源；主线页面仍为占位。 |
| `POST /restrictions`、`DELETE /restrictions/{id}` | 依 §7.5 的 `blocklist`、`cooling_off`、`mute` 和重复删除规则；路由接线与隔离库虚构夹具测试待新增，未验证。 |
| 候选命中、`until` 边界、目标 404 和 gap | 依 §7.5 及 `docs/contracts/T-A209-market-wiring.md` §4；无已合入的端到端测试，未验证。 |
| #335（T-B199）与四项范围 | #335 是策略历史单，与实时行情、市场概览、restrictions、reviews 当前放行条件无直接依赖，移出本门槛，不作判据。 |

## 四、复盘页（reviews）

主线已批准基线只有 `docs/api-contract.md` §7.8 的 reviews 端点骨架。以下内容均为待定：待 #349（@3d93af9c）与 #356/#362 合入，不能作为放行判据。

| 入口 | 待定验收内容 |
|---|---|
| `POST /reviews` | 完整整体替换体、幂等键、本人隔离、`available_at` 及导入批次 `committed_at` 的可见性；响应顶层平铺 `data_status`、`data_as_of`、`gaps`。 |
| `POST /reviews/{id}/versions` | `base_version_no` 乐观并发、空数组清空、不可变快照；四指标 `value=null`、真实 `n` 和 `outcome_metrics.<name>/no_source`。 |
| `GET /reviews`、`GET /reviews/{id}`、`GET /reviews/{id}/versions[/{n}]` | 只读冻结快照，三字段在相应对象顶层且与快照一致；`Evidence` 可解析；不按当前时钟重算。 |
| 手工成交（`import_batch_id` 为空） | `available_at` 规则、成交时间为空的处理及证据来源待上述契约合入后统一验收。 |
| pending 响应 | `data_status=pending`、指标为 `null` 并保留 `trades.import_commit_unproven`/`no_source` gap，依 T-B216 裁定待 #356/#362 合入。 |
| 页面 `/reviews` | 主线仍为占位路由；#333 仅作页面跟进记录，不作契约判据。 |

## 五、可复现验收步骤

以下每项都使用虚构夹具或 mock 栈。测试路径均已用 `git ls-files --with-tree=origin/main` 核实，不存在的测试明确标为待新增。

1. 页面路由。访问 `/terminal`、`/market`、`/restrictions`、`/reviews`，期望页面 HTTP 200。对应 API 分别为 `GET /quotes`、`GET /market/overview`、`GET /restrictions`、`GET /reviews`，期望已接线路由返回 200，JSON 分别断言 `items[]`、`trade_date`、`items[]`、`items[]`。页面端到端测试待新增，未验证。
2. 实时行情。调用 `GET /quotes?codes=999991.SH`、`GET /terminal`、`GET /stream`，期望 200；断言 `items[*].price`、`items[*].data_as_of`、`rows[*].quote`、SSE `quote.data_as_of` 非空，缺源时 `data_status="unavailable"`、`gaps[*].reason="no_source"`，断线不入队。`tests/backend/unit/test_quotes_empty_s3.py` 已存在但未覆盖完整矩阵，其余测试待新增，未验证。
3. 市场概览。调用 `GET /market/overview`，期望 200；断言 `trade_date`、`session`、`indices`、`breadth`、`regime`、`regime_position_range`、`turnover_total`、`data_status`、`data_as_of`、`gaps` 和 `basis` 路径存在。命令为 `PYTHONPATH=src/backend python3 -m pytest -c tests/pytest.ini tests/backend/unit/test_s12_market_public_json.py tests/backend/unit/test_tt99_market_clock_fixed.py -q`。15:00、17:10、BJ 20 码和批次语义测试待新增，未验证。
4. 市场空态与资金流。调用 `GET /market/overview`、`GET /market/sector-flows?kind=industry`，期望 200；断言概览的 `data_status`、`data_as_of`、`gaps` 与主线最小结构一致，资金流的 `items=[]`、`data_as_of=null`、`gaps[*].reason="no_source"`。`tests/backend/unit/test_sector_flows_empty_s3.py` 已存在且命令为 `PYTHONPATH=src/backend python3 -m pytest -c tests/pytest.ini tests/backend/unit/test_sector_flows_empty_s3.py -q`；#352 PIT 仍待合入，未验证。
5. restrictions。调用 `GET /restrictions`、`POST /restrictions`、`DELETE /restrictions/{id}`，期望分别为 200、201、200；断言 `items=[]`、`next_cursor`、`gaps`，重复删除保留 `removed_at` 与 `status="removed"`，跨用户资源为 404。测试待新增，未验证。
6. reviews。逐一调用 `POST /reviews`、`POST /reviews/{id}/versions`、`GET /reviews`、`GET /reviews/{id}`、`GET /reviews/{id}/versions`、`GET /reviews/{id}/versions/{n}`及手工成交入口。期望创建 201、读取 200、冲突 409、他人或不存在资源 404。断言各响应顶层 `data_status`、`data_as_of`、`gaps`，四项 `outcome_metrics.*.value=null`，pending 时保留 `trades.import_commit_unproven`，`Evidence` 的 ID 可解析。主线没有 reviews 路由测试，测试待新增，未验证。

## 六、需用户本人确认

- 真调麦蕊、切 live（`MAIRUI_MODE=live`）和打开盘中定时器，须经用户本人明确批准。未批准时保持离线 replay，live 关闭。
- 本人查看四页真实浏览器布局、空态、`stale`、`partial`、`unavailable` 标签和图表可读性。
- 真实证书行情验证、真实持仓导入、删除用户数据、解除 HALT 或 `backfill --apply` 均须用户本人明确批准。

## 七、未验证参数

| 参数 | 保持方式与依据 |
|---|---|
| U1、U4、U8 字段、单位、覆盖与涨跌停 | 保持 `null` 或 `enabled=false`。#347 仅为候选依据，未合入，不作判据。 |
| F25/G-02 regime、参考区间、覆盖率 | `regime=null`、`regime_position_range=null`，保留 `no_source` gap，待 #359。 |
| BJ 双源同日 20 码门闩 | 默认拦截，待 `docs/contracts/daily-bars-source.md` §10 契约合入。 |
| F21 资金流可见时点 | 未满足 PIT 时 `items=[]` 或字段 `null` 加 `no_source`。#352 仅为候选依据，未合入，不作判据。 |
| 复盘四项指标 | `value=null`、`n=0`（#349@3d93af9c 定稿前口径）、各 `outcome_metrics.<name>/no_source`，待 #349 与 #356/#362。 |

## 八、本地栈大同步放行门槛

- [ ] #359 合入并完成 `/market/overview` 的新增字段、空态、批次键和 `MarketBasis` 计数验收，#280 不作为依据。
- [ ] restrictions 路由、复盘路由和四页页面接线完成，逐项测试通过。
- [ ] #349 与 #356/#362 同批合入且全绿，复盘 pending 保留 `trades.import_commit_unproven`。
- [ ] 15:00、17:10、PIT、证书隔离、BJ 默认拦截、Decimal 单位和前视排除均有可复现 HTTP 断言。
- [ ] 未验证参数仍保持关闭或 `null+gap`，仓库无真实交易数据、证书或个人信息。
- [ ] 真调麦蕊、`MAIRUI_MODE=live` 和盘中定时器仅在用户本人明确批准后开启，未批准时离线 replay。
- [ ] `git diff --check`、`python3 scripts/ci/check_contract.py`、目标后端/前端测试和 secret scan 全部通过。
