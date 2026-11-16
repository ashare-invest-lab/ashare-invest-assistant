# T-R79｜模拟跟踪真实基准口径卡（draft）

交付：[benchmark_spec.md](benchmark_spec.md)。基线 `origin/main=95967e1`，分支 `docs/T-R79`；仅文档，不改变运行时或API。

- §1：逐项核对 tracking 四文件、plan/API契约、多源/日历契约、T-R71四卡、团队T-R72 B11/B12及F50。
- §2–§6：22条可实现规则，每条附【虚构】手算/边界/缺数例；盘后统一D1开盘至D1/D5/D20收盘，主辅独立，行业未验证。
- §7：U01–U12共12项，T-R79b查证为**已验证 0／部分核实 6／未验证 6**（互斥计数）；部分核实的整项状态仍为未验证，尚未整项验证共12项。§8保留原4个官方URL及6个价格指数元数据值；§9的8条待裁定由T-A190处理。
- 现引擎固定000300.SH、采用简单收益差；缺source/版本/定稿证明、辅基准、完整指数日线及盘中复权桥。现服务冻结unavailable与契约五日重算存在差异。
- 全收益接线未核；价格指数超额含分红偏差。候选信号及模拟结果不构成荐股，不承诺收益。

T-R79原单已登记两份Markdown的horizon_inventory.scope_snapshot；T-R79b仅改本目录的本文件及benchmark_spec.md，不改库存登记或策略身份。R-R1既有登记缺口仍由#178处理。

## T-R79b公开查证（2026-11-15）

- U01/U02/U03/U07/U08/U09部分核实：官方代码与供应商后缀分开；日频发布不等于17:10定稿；休市通知仅作对应年份参照；H00300/H00985存在、基日与发布日期有官方单张支持；更名实例不外推本卡历史映射；实时频率以接口定义为准。
- U04/U05/U06/U10/U11/U12仍未验证：性质为内部实现/数据验证，公开出处不适用；分别需要因子/可成交事实、快照重放、完整性门槛裁定、补算时钟裁定、hold样本外校准、辅槽及分组展示验收。
- 官方URL、日期、每条不超过60字的摘录和剩余证据列于[登记表及出处](benchmark_spec.md#7-参数出处登记及未验证计数)。逐项URL、HTTP状态、检索词和访问限制另存团队报告T-R79b.md（仓库外）。
- 规则语义、虚构用例数值和D01–D08均保持原文；未读取凭据或调用麦蕊接口。

## T-R79b验收（2026-11-15）

由 `git ls-files 'docs/strategies/**/check_*.py' 'docs/strategies/check_*.py'` 枚举16个脚本，使用任务指定的临时虚拟环境Python，设置 `PYTHONDONTWRITEBYTECODE=1`，普通与 `-O` 各跑一遍，共32次、28次rc=0。进程使用最小环境，不传数据库地址；不加载凭据，不联网取行情。完整stdout/stderr日志留临时目录。

| checker（相对 docs/strategies） | 普通rc | -O rc |
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

两种允许例外已核实：check_horizons仅报告R-R1的8个既有未登记文件，没有本单文件漏登；check_f21_ready仅报告DATABASE_URL未设置，未连库。未处理R-R1（#178负责）。其余全部通过，普通与优化模式一致。

`git diff --check`无输出；新增文本禁止绝对路径检索为空。与HEAD逐项比较确认P01–P05、D01–D08、§8及全部虚构用例原文不变；§2–§6仅追加出处边界句。U项互斥计数0/6/6，6条内部项均列所需证据。仓库只改本目录两份文档，净增少于800行；未生成.last.md。

本次文档检查不代表真实数据就绪；剩余接线、日历覆盖、定稿/重发证据、分钟桥、偏差量化与hold校准仍未验证。

已尝试本次git add和指定消息的git commit，两者均rc=128：Git元数据文件系统只读，无法创建index.lock。未形成提交，改动保留；未push、stash或绕过hook。
