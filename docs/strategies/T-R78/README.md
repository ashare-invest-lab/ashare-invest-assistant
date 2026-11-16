# T-R78｜horizon 输入特征口径卡

状态：**定稿待治理员批**；lifecycle 保持 **draft**，G7：☐。原盘点基线 origin/main `95967e1`；T-R78b 修订基点 #205 `7fe7817`，分支 `docs/T-R78`。仅解释候选信号，不荐股、不承诺收益。

- [口径卡](horizon_inputs_spec.md)：25项输入盘点、15项缺失/未接卡片（含FIFO）、分位装配、时点与qfq@as_of、【虚构】手算；§2.0共同裁定、§6十二项裁定及解除条件、§7实施边界。
- 配置内24项：已接10／未接0／无实现14；加入后补F49后25项：**已接10／未接1／无实现14**。文档定稿不代表这些生产/接线缺口已完成。
- ATR%与交易频率已被既有分类器文档排除，不新造字段、不计入25项；Amihud保留键/null缺口，生产算法暂不排。
- 参数状态：Q01–Q06、Q08–Q10仍有未验证分支及解除条件；Q07/Q11语义定稿但实现缺口仍在；Q12职责定稿，历史重放仍未验证。
- `docs/strategies/P2N-R10/horizon_inventory.json` 已登记两份文档，T-R78b无需改登记、不新增文件。

## 变更记录

- **T-R78b（2026-11-15）**：并入架构师 T-A188 裁定（团队报告 T-R78.md §T-A188，已并入本节），完整转述见口径卡 §2.0、§6；原待裁定表移至 §6 并改为问题摘要/结论/正文影响三层，原实施边界顺延 §7。保留暂缓项“未验证”与解除条件，不新增阈值/公式。
- 已用本地 `rg` 核对 `docs/api-contract.md`，`GET /horizon-assessments` 实际位于 **§7.4**，规格引用已统一。
- 引用 **PR #219 `docs/contracts/horizon-inputs-base.md`**（本地 `origin/docs/T-A192`）：A0/A1六项裁定、显式as_of、完成证据E、两张追加表、PN-03 `read_adjustment_factors`、缺因子不补1；旧实现差异保留为缺口，真实特征接入仍须规格进入main。
- 规格定稿与治理批准分开：状态“定稿待治理员批”，lifecycle=draft，G7保持☐；不代表实现/真实数据/收益验证或生命周期晋级。

## 验收

对 `git ls-files 'docs/strategies/**/check_*.py' 'docs/strategies/check_*.py'` 列出的每个checker，使用 `/tmp/ckvenv/bin/python` 普通与 `-O` 各跑一次；设置 `PYTHONDONTWRITEBYTECODE=1`。
运行时清空继承环境，只保留最小PATH与该变量，不读取凭据文件、不访问数据库或数据供应商；公开来源checker默认离线，不传fetch选项。无新增checker。

T-R78b实际复验：16个checker×两模式＝32次，28次rc=0；以下两项在普通/-O模式均rc=1，其他14项在两模式均rc=0，无额外失败。R-R1报错extra仅含该目录八个文件，没有本单路径。

| checker | 普通 | -O | 既有原因 |
|---|---|---|---|
| `P2N-R10/check_horizons.py` | 1 | 1 | R-R1八个文件未登记，关联#178；不越界补登记 |
| `check_f21_ready.py` | 1 | 1 | 未提供数据库连接配置；按任务限制不连库 |

可复现命令：

```bash
for checker in $(git ls-files 'docs/strategies/**/check_*.py' 'docs/strategies/check_*.py'); do
  env -i PATH=/tmp/ckvenv/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /tmp/ckvenv/bin/python "$checker"
  env -i PATH=/tmp/ckvenv/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /tmp/ckvenv/bin/python -O "$checker"
done
```

本轮文档验收：指定旧引用/旧API节号及禁止的本机绝对路径扫描均无命中；`git diff --check`无输出，仅改本目录两份已有文档，净增≤400行，无新增文件或临时尾稿。

未解决：口径卡§6列明的真实语义/参数/事件证据，以及底座存储、特征生产与接线；合成PASS不能解除。尚未执行真实库、供应商或收益验证。
