# 策略详情与知识卡关联最小契约（T-A151）

状态：draft，架构裁定，不代表已实现。基线 main `4aae38a`。
输入：前端 T-F40 报告（`/workspace/team/reports/T-F40.md`）「待编排者裁定」1–5。本文只补 `docs/api-contract.md` §7.4；本文与 §7.4 不一致处以本文为准，§7.4 原文不改。引用只写文件名、函数名、表名。

原则：只读、最小可用；不新增表或迁移；复用 `api/v1/strategy_cards.py` 中已有函数的查询与投影。

## 0. 核对结论（依据）

- **表**（`db/tables/strategy.py`）：
  - `strategies`：头表，`key` 唯一，`owner_user_id` 可空，`current_version_id`。
  - `strategy_versions`：`(strategy_id, version_no)` 唯一；`card_version_id` 可空，外键指向 `strategy_card_versions.id`；另有 `parent_version_id`、`lifecycle`、`published_at`、`param_hash`。
  - `strategy_cards`：`key` 唯一，`owner_user_id`，`current_version_id`。
  - `strategy_card_versions`：`(card_id, version_no)` 唯一，内容不可变。
  - `strategy_lifecycle_events`：只追加；字段 `strategy_version_id`、`from_state`、`to_state`、`reason`、`trigger`（admin 或 health_machine）、`actor_id`、`at`。
- **已有路由**（`api/v1/strategy_cards.py`）：
  - 有：`strategy_list`、`version_detail`、`card_list`、`card_detail`（也服务 `/strategy-cards/{id}/versions/{no}`）、`card_history`。
  - 没有：`GET /strategies/{id}`、版本列表、lifecycle-events、按 card_version_id 取卡。
  - 可见性统一用 `visible`：owner 为空，或 owner 是本人。
- **正式导入** `strategy/cards/persistence.import_batch`：同一个 `key` 同时建卡头和策略头；每导入一个卡版本，就新建一个同号策略版本，并写入 `card_version_id`。
- **派生** `strategy/instances/creation.derive`：新建私有策略头（`key=private_<hex>`，`copied_from_version_id`），策略版本号为 1；`card_version_id` 继承母版本，`parent_version_id` 指向母版本。
- **生命周期事件写入方**：管理员转换走 `strategy/reviews.change_lifecycle`。健康状态机写入的完整性未验证。

## 1. 通用约定

- 前置条件：需要登录，且账号已批准。
  - 未登录：`401 AUTH_REQUIRED`。
  - 账号未批准：`403 ACCOUNT_NOT_APPROVED`。
- 资源不存在、不可见、或不属于路径中的父资源：一律 `404 NOT_FOUND`，不暴露他人私有资源是否存在。
- 路径 UUID 非法：`400 VALIDATION_ERROR`。
- 列表按 §1.2 游标分页（limit 默认 50、最大 200）。游标绑定用户、路径参数和筛选参数；不匹配时返回 `400 INVALID_CURSOR`。
- 只返回本文列出的字段。他人标识（`actor_id`、`published_by`、`lifecycle_changed_by`、`created_by`、`owner_user_id`）一律不返回。

## 2. GET `/strategies/{id}` 🔒（T-F40 待裁定 1）

单对象，不分页。元素结构与 `strategy_list` 的列表元素**完全相同**，实现上复用其投影和健康查询：

| 字段 | 类型 | 可空 | 来源 |
|---|---|---|---|
| id | string(uuid) | 否 | `strategies.id` |
| key | string | 否 | `strategies.key` |
| name | string | 否 | `strategies.name` |
| horizons | horizon[] | 否 | `strategies.horizons` |
| risk_level | card_risk_level | 否 | 当前版本关联卡版本的 `fields.risk_level`；未关联时为 `normal`（同 `strategy_list`） |
| current_version | `{id, version_no, lifecycle}` | 否 | `strategies.current_version_id` 关联 `strategy_versions` |
| health | `{state, weight: string(decimal), n}` | 是 | 当前版本 `strategy_health_daily` 中 `as_of_date` 最新的一条；没有记录时为 null（T-A13 ①） |

- 空态：头存在但 `current_version_id` 为空时，返回 `404 NOT_FOUND`，与 `strategy_list` 的内连接口径一致，不另造空对象。
- 错误：通用错误，加 `404 NOT_FOUND`。

## 3. GET `/strategies/{id}/versions` 🔒（T-F40 待裁定 2）

按 §1.2 分页，排序固定为 `version_no desc`（`(strategy_id, version_no)` 唯一，排序稳定）。元素只给摘要；配置仍走已有的 `version_detail`。

| 字段 | 类型 | 可空 | 来源 |
|---|---|---|---|
| id | string(uuid) | 否 | `strategy_versions.id` |
| version_no | int | 否 | `strategy_versions.version_no` |
| lifecycle | lifecycle | 否 | `strategy_versions.lifecycle` |
| is_current | boolean | 否 | `strategy_versions.id` 是否等于 `strategies.current_version_id` |
| card_version_id | string(uuid) | 是 | `strategy_versions.card_version_id`；为 null 表示未关联知识卡 |
| parent_version_id | string(uuid) | 是 | `strategy_versions.parent_version_id` |
| published_at | string(datetime) | 是 | `strategy_versions.published_at` |
| created_at | string(datetime) | 否 | `strategy_versions.created_at` |

- 可见性：先检查策略头的 `visible`。各版本不因 `lifecycle`（draft、retired 等）被额外隐藏。lifecycle 与能不能运行无关，能否运行仍按 §6.0A 判定。
- 空态：可见策略没有版本时，返回 `200 {"items": [], "next_cursor": null}`。
- 错误：通用错误，加 `404 NOT_FOUND`、`400 INVALID_CURSOR`。

## 4. GET `/strategies/{id}/lifecycle-events` 🔒（T-F40 待裁定 3）

返回该策略所有版本的事件，按 §1.2 分页，排序固定为 `at desc, id desc`。可选筛选 `?version_id=`，该版本必须属于此策略，否则 `404 NOT_FOUND`。

- §7.4 原有的 `GET /strategies/{id}/versions/{vid}/lifecycle-events` 定为本接口的等价写法，即 `version_id={vid}`；两者共用一个查询，返回相同元素，游标不能互换。

| 字段 | 类型 | 可空 | 来源 |
|---|---|---|---|
| id | string(uuid) | 否 | `strategy_lifecycle_events.id` |
| version_id | string(uuid) | 否 | `strategy_lifecycle_events.strategy_version_id` |
| version_no | int | 否 | 关联 `strategy_versions.version_no` |
| from_state | lifecycle | 是 | `from_state`；首个事件可以为 null |
| to_state | lifecycle | 否 | `to_state` |
| trigger | `"admin"`\|`"health_machine"` | 否 | `trigger` |
| at | string(datetime) | 否 | `at` |

- 不返回 `actor_id`。`reason` 是管理员自由文本，是否对普通用户展示待裁定（§8 第 2 项），裁定前不返回。
- 空态：策略可见但没有事件时，返回空分页。不得根据当前 lifecycle、版本创建或派生关系合成事件。派生版本继承母版本的 `lifecycle`，但没有自己的事件，这是预期行为。
- 错误：通用错误，加 `404 NOT_FOUND`、`400 INVALID_CURSOR`、`400 VALIDATION_ERROR`（version_id 不是 UUID 时）。

## 5. GET `/strategy-card-versions/{card_version_id}` 🔒（T-F40 待裁定 5）

按卡版本 UUID 精确读取，单对象，不分页。

- 响应：与 `card_detail` 的返回体**相同**（2.5.14 B 节字段展开，加 `field_epistemic`、`refs`、`validation_summary`、`risk_level`、`gates_missing`），另外在顶层加三个字段：

| 字段 | 类型 | 可空 | 来源 |
|---|---|---|---|
| card_version_id | string(uuid) | 否 | `strategy_card_versions.id` |
| card_id | string(uuid) | 否 | `strategy_card_versions.card_id` |
| version_no | int | 否 | `strategy_card_versions.version_no` |

- 可见性：经 `card_id` 检查 `strategy_cards.owner_user_id` 的 `visible`。能读关联策略不等于能读这张卡。
- 不回退：该版本不存在时返回 `404 NOT_FOUND`，不改返卡的当前版本。
- 客户端：策略版本的 `card_version_id` 为 null 时，显示「未关联知识卡」，不发这个请求。
- 实现提示：抽出 `card_detail` 的投影来复用，不复制一份。
- 错误：通用错误，加 `404 NOT_FOUND`。

## 6. 知识卡与策略的关联裁定（T-F40 待裁定 4）

1. **真源**：唯一读取真源是 `strategy_versions.card_version_id → strategy_card_versions`。不得用 `key`、名称或版本号去猜对应关系；`import_batch` 用同一个 key 只是导入约定，派生策略的 key 是 `private_…`。卡的内容真源是 `docs/strategies/cards`，经 cards-import 写入 `strategy_card_versions`（内容不可变）。
2. **基数**：
   - 策略版本对卡版本：0 或 1（`card_version_id` 可空；用户私有、没有卡的策略为 null）。
   - 卡版本对策略版本：1 对多（正式导入 1 个，再加上 `derive` 派生出的多个私有版本）。
   - 头层面：正式 builtin 卡与正式策略约定 1:1（同 key）；含派生时，1 张卡对 N 个策略头。
3. **版本对应**：按版本绑定，不按头绑定。策略详情、`risk_level`、卡正文都按**所选策略版本**绑定的卡版本读，不跟随卡的 `current_version_id`。卡出新版本后，只有正式导入新建的同号策略版本才绑定新卡版本；旧策略版本和派生版本保持原绑定。
4. **从卡跳到策略**：新增 `GET /strategy-cards/{id}/strategies` 🔒。
   - 分页：按 §1.2，排序固定为 `strategy_versions.created_at desc, strategy_versions.id desc`。
   - 元素：`{strategy_id, strategy_name, version_id, version_no, card_version_id, lifecycle, is_current}`，都不可空。
   - 范围：返回该卡所有卡版本关联的策略版本，只保留策略头 `visible` 的那些。
   - 空态：卡可见但没有可见关联时，返回空分页；卡不存在或不可见时返回 `404`。
   - 不给卡摘要加单值 `strategy_id`。前端看到多条时让用户选择，不默认取第一条。

## 7. 不在本单范围

- `card_history` 目前返回不分页的数组，与 §1.2「列表均分页」不一致，另行统一。
- `strategy_list` 的排序目前是 `strategies.id`，与 §1.2 默认排序不同，本文不改。
- 写接口、管理端 lifecycle 和健康状态机都不改。

## 8. 待编排者裁定

1. 认可 §6 的关联裁定（版本绑定、真源为 `card_version_id`、卡对策略 1:N）。
2. lifecycle `reason` 是否对普通用户展示。建议展示，因为它是管理员针对策略写的说明，不含个人信息；前提是先确认 `change_lifecycle` 的入参约束，未验证。
3. `/strategies/{id}` 在 `current_version_id` 为空时返回 404，还是返回 200 空态。本文取 404，与列表内连接一致。
4. 两条 lifecycle-events 路径并存，还是在 v0.3 去掉版本级路径。
5. 后端实现的派单范围：3 个 GET 加卡反查 1 个，共 4 个只读路由，加对应的 selfchecks；前端随后接 T-F40 的待裁定 1–5。
