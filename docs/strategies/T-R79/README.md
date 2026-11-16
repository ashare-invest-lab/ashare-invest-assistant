# T-R79｜模拟跟踪真实基准口径卡（draft）

交付：[benchmark_spec.md](benchmark_spec.md)。基线 `origin/main=95967e1`，分支 `docs/T-R79`；仅文档，不改变运行时或API。

- §1：逐项核对 tracking 四文件、plan/API契约、多源/日历契约、T-R71四卡、团队T-R72 B11/B12及F50。
- §2–§6：22条可实现规则，每条附【虚构】手算/边界/缺数例；盘后统一D1开盘至D1/D5/D20收盘，主辅独立，行业未验证。
- §7：12项未验证参数或口径组；§8：4个已核对官方URL，基日/基点/发布日共6个值有据；§9：8条待裁定。
- 现引擎固定000300.SH、采用简单收益差；缺source/版本/定稿证明、辅基准、完整指数日线及盘中复权桥。现服务冻结unavailable与契约五日重算存在差异。
- 全收益接线未核；价格指数超额含分红偏差。候选信号及模拟结果不构成荐股，不承诺收益。

文件登记只为本单新增两份Markdown添加horizon_inventory.scope_snapshot；不新增策略身份、不修R-R1既有登记缺口（另由#178处理）。

## 验收（2026-11-15）

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

`git diff --check`无输出；两份新增文件另作no-index空白检查也无输出。新增文本禁止路径检索为空；规则/用例覆盖22/22，未验证组12、待裁定8。库存JSON对比确认只增加本单两条scope记录，其余字段不变。无运行时验收或真实数据就绪结论；仓库未生成.last.md。

已尝试git add及指定消息的git commit，两者均rc=128：Git元数据所在文件系统只读，无法创建index.lock。未形成提交，改动完整保留；未push、stash或绕过hook。三文件净增310行，未超过800行。
