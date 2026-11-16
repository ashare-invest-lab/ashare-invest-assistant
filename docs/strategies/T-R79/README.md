# T-R79｜模拟跟踪真实基准口径卡（draft）

交付：[benchmark_spec.md](benchmark_spec.md)、[只读SQL草稿](readonly_checks.sql)。代码基线`origin/main=95967e1`，本次核证基于分支`docs/T-R79`的`0609313`；仅文档，不改变运行时或API。

- §1：逐项核对tracking、plan/API契约、多源/日历契约、T-R71四卡及既有T-R72资料。
- §2–§6：22条规则及【虚构】手算/边界/缺数例原文不变；§8官方元数据、§9 D01–D08待裁定原文不变。
- §7累计：**已验证 0／部分核实 11／未验证 1**（12项互斥计数）；部分核实包括T-R79b的6项公开事实及本次5项源码逻辑，尚未整项验证仍为12项。
- 现引擎固定000300.SH；缺source/版本/定稿证明、辅基准和整窗完整性门槛。unavailable冻结与契约五日重算有差异，盘中复权桥及全收益接线未核。
- 价格指数超额含分红偏差；模拟结果不代表实际收益，不构成荐股或收益承诺。

## T-R79c源码核证（2026-11-15）

本次仅读源码、测试定义与docs，未运行会建库/连库的后端测试。**“已核实（源码）”只证明实现逻辑和测试断言，不证明真实数据链路、参数校准或实库验收。** §7 C04/C05/C06/C10/C11/C12逐项列出完整文件、行号、测试名和剩余证据。

| 登记项 | 本次整项结论 | 已核边界与剩余问题 | SQL |
|---|---|---|---|
| U04 | 未验证（部分源码核实） | 因子时点/qfq锚定、可成交状态分流已核；复杂权息、事实/持仓接线未验 | Q01/Q02 |
| U05 | 未验证（部分源码核实） | 摘要、算法及原始价格快照已核；整窗source/data_version/manifest与同版重算未验 | Q03/Q05 |
| U06 | 未验证（部分源码核实） | 当前两端/可见性及缺基准分流已核；整窗缺日门槛待D03及实库覆盖 | Q04 |
| U10 | 未验证（部分源码核实） | cutoff钳制、跳过非pending及冻结断言已核；五日重算未实现验收，时钟待D04 | Q05/Q06 |
| U11 | 未验证 | 1/2/5初值来源与闭区间测试已核；校准有效性需真实样本分层、时间外留出及敏感性复测 | Q07仅盘点样本 |
| U12 | 未验证（部分源码核实） | 现有去重/版本周期scope分组/各自n已核；辅槽/配对n/展示扩展待D02/D07及验收 | Q07 |

六项本次计数：已验证0、部分源码核实5、未验证1。U11按校准目标归未验证，未把“有常量/边界测试”算作校准有效。U01/U02/U03/U07/U08/U09沿用T-R79b公开事实部分核实，具体官方出处仍在§7，不外推为仓库接线证据。

SQL共7条，均为带参数的SELECT/WITH；逐条标迁移/模型出处及期望判读，无真实私有样本。**草稿，未执行；仅供运维在本地栈只读执行，执行需另行授权。** 当前库存查询不能恢复历史修订、证明五日作业或校准有效。

库存仅在`horizon_inventory.scope_snapshot`登记本单新增的`readonly_checks.sql`，未补登R-R1或改变策略身份。逐项查证和验收记录另存团队报告T-R79c.md（仓库外）。

## T-R79c验收（2026-11-15）

按`git ls-files 'docs/strategies/**/check_*.py' 'docs/strategies/check_*.py'`枚举脚本，使用任务指定临时虚拟环境Python，设置`PYTHONDONTWRITEBYTECODE=1`，普通与`-O`各跑。最小环境不传数据库地址，禁止凭据读取/网络及数据库驱动导入；不执行SQL。结果如下。

| checker（相对docs/strategies） | 普通rc | -O rc |
|---|---|---|
| F23-v4/check_q5_evidence_seeds.py | 0 | 0 |
| P2N-R10/check_horizons.py | 1 | 1 |
| S2-7/check_public_sources.py | 0 | 0 |
| T-R21/check_T-R21.py | 0 | 0 |
| T-R22/check_f23.py | 0 | 0 |
| T-R23/check_f23_v2.py | 0 | 0 |
| T-R23/check_f23_v2_1.py | 0 | 0 |
| T-R62/check_f23_v3.py | 0 | 0 |
| check_f21_ready.py | 1 | 1 |
| check_p2n01_dimension_mapping.py | 0 | 0 |
| golden/check_P2N-09.py | 0 | 0 |
| golden/check_P2N-R08.py | 0 | 0 |
| golden/check_P2N-R09.py | 0 | 0 |
| golden/check_T-R15.py | 0 | 0 |
| golden/check_T-R73.py | 0 | 0 |
| golden/check_exdiv_T-R15.py | 0 | 0 |

共16个脚本、32次：28次rc=0。check_horizons两种模式均仅报R-R1的8个既有未登记文件（#178），未漏本单SQL；check_f21_ready两种模式均仅报DATABASE_URL未设置，未连接数据库。其余全部rc=0，普通与优化模式一致。

`git diff --check`无输出；新增内容的绝对路径检索为空；SQL危险关键字检索仅命中注释中的列名说明，去注释后无命中。静态检查确认7条均以SELECT/WITH开头，未执行SQL；P01–P05、其他6项U、§1–§6、§8、§9（含D01–D08）逐字保持原样；未生成.last.md。

尚未整项验证的12项保持未验证边界；真实数据接线、单源版本/定稿/日历、整窗门槛、五日补算、辅槽展示及hold校准仍需后续验收或裁定。

已尝试对本单四文件执行git add及指定消息的git commit，均rc=128：Git元数据文件系统只读，不能创建index.lock；未形成新提交，改动完整保留。未push、stash或绕过hook。
