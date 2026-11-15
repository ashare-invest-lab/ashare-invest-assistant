# T-R71 验收记录

## 本轮续任务：T-R72 P1 对照验收

本轮仅做文档接口依赖映射。各卡新增 12 条 B01–B12 对照；README 增加 P1 列、共同前置及建议接入顺序，补齐日线 17:10 后实际定稿、plrq ≤ 信号日及禁止 jzrq 回填。四卡 lifecycle 仍为 draft；不调用麦蕊、不联网、不读凭据/数据库/私有样本，不暂存、不提交、不推送。

以下命令均在工作树执行。Python 使用显式无凭据环境并禁写字节码，不加载应用或数据库；未运行前轮数据库 CLI。

| 本轮命令/检查 | rc | 结果 |
|---|---|---|
| `python3 docs/strategies/P2N-R10/check_horizons.py` | 0 | PASS：192 个 scope 文件、45 个身份、23 个来源身份文件、8 项篡改拒绝 |
| `python3 -O docs/strategies/P2N-R10/check_horizons.py` | 0 | PASS：同上，优化模式仍校验拒绝 |
| `python3 docs/strategies/P2N-R10/test_tracking_unknown_pyc.py` | 0 | PASS：无 pyc 对照普通/-O 均 rc=0；非 Git 下植入 pyc 普通/-O 均 rc=1，命中 tracking_unknown（预期拒绝） |
| `python3 -O docs/strategies/P2N-R10/test_tracking_unknown_pyc.py` | 0 | PASS：同上 |
| 任务指定绝对路径 rg 原式 | 1 | 空输出；rc=1 表示没有匹配，满足要求 |
| `git diff --check` | 0 | 无空白错误；未跟踪 T-R71 文档另核尾空白 |
| 依赖表与短名单结构核对 | 0 | 四卡各 12 条、5 列，B01–B12 各一次；短名单 7 列；PIT/定稿/draft 齐全 |
| 本轮修改范围核对 | 0 | inventory 相对本轮开始仅增 T-R71/.last.md 的 scope 与刷新清单登记；未改身份、checker 或 P2N-R10 README |

本轮结果：任务指定验收通过；接口接入、全历史覆盖、PIT 修订可见性、指数与行业基准仍按单卡标记“未验证/未接/部分”，未做行情复测。新增 .last.md 后 scope 从前轮 191 变为 192，身份不变。

下文为前轮历史记录，不表示本轮再次执行；前轮数据库 CLI 的两次失败仍未解决，本轮不把它们改标通过。前轮暂存/提交失败不作为本轮解除条件，当前由研究员提交。

## 前轮验收范围

普通模式与 -O 均采用临时虚拟环境的 python3（3.12.16），依赖为缓存中的 PyYAML 6.0.3；不改仓库依赖。每次子进程均使用不含数据库连接或凭据的显式环境。网络安装依赖不可用后，直接使用已有依赖缓存；未调用行情接口。

## 验收记录

| 命令 | rc | 说明 |
|---|---|---|
| `python3 docs/strategies/F23-v4/check_q5_evidence_seeds.py` | 0 | 通过 |
| `python3 -O docs/strategies/F23-v4/check_q5_evidence_seeds.py` | 0 | 通过 |
| `python3 docs/strategies/P2N-R10/check_horizons.py` | 0 | 通过 |
| `python3 -O docs/strategies/P2N-R10/check_horizons.py` | 0 | 通过 |
| `python3 docs/strategies/S2-7/check_public_sources.py` | 0 | 通过 |
| `python3 -O docs/strategies/S2-7/check_public_sources.py` | 0 | 通过 |
| `python3 docs/strategies/T-R21/check_T-R21.py` | 0 | 通过 |
| `python3 -O docs/strategies/T-R21/check_T-R21.py` | 0 | 通过 |
| `python3 docs/strategies/T-R22/check_f23.py` | 0 | 通过 |
| `python3 -O docs/strategies/T-R22/check_f23.py` | 0 | 通过 |
| `python3 docs/strategies/T-R23/check_f23_v2.py` | 0 | 通过 |
| `python3 -O docs/strategies/T-R23/check_f23_v2.py` | 0 | 通过 |
| `python3 docs/strategies/T-R23/check_f23_v2_1.py` | 0 | 通过 |
| `python3 -O docs/strategies/T-R23/check_f23_v2_1.py` | 0 | 通过 |
| `python3 docs/strategies/T-R62/check_f23_v3.py` | 0 | 通过 |
| `python3 -O docs/strategies/T-R62/check_f23_v3.py` | 0 | 通过 |
| `python3 docs/strategies/check_f21_ready.py` | 1 | 未通过：缺少 DATABASE_URL，默认 CLI 需要目标库；没有读取凭据或连接真实库 |
| `python3 -O docs/strategies/check_f21_ready.py` | 1 | 未通过：缺少 DATABASE_URL，默认 CLI 需要目标库；没有读取凭据或连接真实库 |
| `python3 docs/strategies/check_p2n01_dimension_mapping.py` | 0 | 通过 |
| `python3 -O docs/strategies/check_p2n01_dimension_mapping.py` | 0 | 通过 |
| `python3 docs/strategies/golden/check_P2N-09.py` | 0 | 通过 |
| `python3 -O docs/strategies/golden/check_P2N-09.py` | 0 | 通过 |
| `python3 docs/strategies/golden/check_P2N-R08.py` | 0 | 通过 |
| `python3 -O docs/strategies/golden/check_P2N-R08.py` | 0 | 通过 |
| `python3 docs/strategies/golden/check_P2N-R09.py` | 0 | 通过 |
| `python3 -O docs/strategies/golden/check_P2N-R09.py` | 0 | 通过 |
| `python3 docs/strategies/golden/check_T-R15.py` | 0 | 通过 |
| `python3 -O docs/strategies/golden/check_T-R15.py` | 0 | 通过 |
| `python3 docs/strategies/golden/check_exdiv_T-R15.py` | 0 | 通过 |
| `python3 -O docs/strategies/golden/check_exdiv_T-R15.py` | 0 | 通过 |

共15个 check_*.py，普通/-O共30次：28次 rc=0，check_f21_ready.py 两次 rc=1。因此用户要求的“全部 rc=0”**尚未满足**。未修改既有 checker、没有将失败改标通过。

scripts 目录以 checker 文件名及正文中的 strategy/strategies/策略 搜索，未发现专属策略 checker；两个普通测试辅助文件的文字匹配不作为独立 checker。secret_scan 单独执行并记录。

## 补充离线验证

| 命令 | rc | 说明 |
|---|---|---|
| `python3 docs/strategies/T-R28/test_check_f21_ready.py` | 0 | 原有阈值锁定、哈希篡改、CLI/环境覆盖拒绝、5通过/4不通过边界；不替代数据库CLI验收 |
| `python3 -O docs/strategies/T-R28/test_check_f21_ready.py` | 0 | 原有阈值锁定、哈希篡改、CLI/环境覆盖拒绝、5通过/4不通过边界；不替代数据库CLI验收 |

## 文件与提交检查

| 命令/检查 | rc | 说明 |
|---|---|---|
| `bash scripts/ci/secret_scan.sh files`（下述8文件） | 0 | 8个文件版本，阻断0、警告0；未采用空暂存区扫描冒充覆盖 |
| `git diff --check` | 0 | 已跟踪差异无空白错误；新增文件另逐行检查无尾空白 |
| 任务指定的绝对路径 rg 检查 | 1 | 空输出；rg 的1表示没有匹配，满足本项要求 |
| `git add docs/strategies/T-R71 docs/strategies/P2N-R10/horizon_inventory.json docs/strategies/P2N-R10/README.md` | 128 | 共享Git目录只读，无法创建index.lock；尚未暂存 |
| `git commit -m "docs(T-R71): 每日决策候选策略短名单 4 张（草稿）"` | 128 | 共享Git目录只读，无法创建index.lock；本地提交未完成，未推送 |

密钥扫描的完整文件列表：docs/strategies/T-R71/README.md、S-01_st_pullback_ma.md、S-02_st_oversold_rebound.md、S-04_st_broken_board.md、W-02_sw_breakout.md、acceptance.md（后五个同目录），以及 docs/strategies/P2N-R10/README.md、horizon_inventory.json（后一个同目录）。环境变量仅配置可写临时缓存、离线依赖与虚拟解释器；没有读取环境文件。

最终结论：文档产物、census及文件检查完成；数据库checker两次未通过，全部rc=0门槛未满足；Git索引无法写入，本地提交未完成。解除需要提供可用的无凭据验证环境/明确的离线验收口径，以及可写的Git元数据目录。

## 解释边界

census 当前为191个 scope 文件，仍为45个身份记录、23个源身份文件，8种变异拒绝；新增草稿没有正式导入围栏，不新增运行身份。基线未登记的55个既有辅助文件仅在 inventory 补登记。

文档 checker 不等于真实日K复测或 G1–G7；本轮策略生命周期全部为 draft。
