# T-R78｜horizon 输入特征口径卡

状态：**draft**；基线origin/main `95967e1`，分支`docs/T-R78`。本单仅文档，不产生候选信号，不荐股、不承诺收益。

- [口径卡](horizon_inputs_spec.md)：25项输入盘点、15项缺失/未接卡片（含FIFO）、分位装配、时点与qfq@as_of约束、【虚构】手算及12条待裁定。
- 配置内24项：已接10／未接0／无实现14；加入裁定要求的F49后25项：**已接10／未接1／无实现14**。
- ATR%与交易频率在规划有提及，但已被既有分类器文档排除，单列说明、不新造字段、不计入25项。
- 参数状态：供应商公式/单位、原文建议与来源不明参数保留“未验证”；已有裁定不擅自改动。待裁定交编排者转架构师。
- 登记仅增加本单两个文档到`docs/strategies/P2N-R10/horizon_inventory.json`，不补登记其他任务文件。

## 验收

对`git ls-files 'docs/strategies/**/check_*.py' 'docs/strategies/check_*.py'`列出的每个checker，使用`/tmp/ckvenv/bin/python`普通与`-O`各跑一次；设置`PYTHONDONTWRITEBYTECODE=1`。
运行使用清空继承环境后的最小PATH与该变量，确保不取得数据库连接配置；不读取凭据文件、不访问数据库、不调用数据供应商。没有本单新增checker。
实际运行16个checker×两种模式＝32次；28次rc=0。以下仅两项在两种模式均rc=1，其余14项在两种模式均rc=0：

| checker | 普通 | -O | 原因 |
|---|---|---|---|
| `P2N-R10/check_horizons.py` | 1 | 1 | main已有R-R1八个文件未登记；报错extra只含R-R1，无本单路径 |
| `check_f21_ready.py` | 1 | 1 | 未提供数据库连接配置；按任务限制未访问数据库 |

已对照origin/main确认R-R1八个文件存在但未登记，两份checker与main一致；这两类既有红依赖 **#178** 修复。本单只登记自身两份文档。
另用离线算术复核F01/F04/F06/F09及FIFO部分卖出、送转、半入取整示例，结果相符；配置24键全部在盘点表中。
`git diff --check`无输出；新增内容路径扫描无命中；本单净增低于800行（L-042），只涉及本目录及指定inventory登记。

可复现的checker调用（不继承连接配置，不需要凭据或数据源访问）：

```bash
for checker in $(git ls-files 'docs/strategies/**/check_*.py' 'docs/strategies/check_*.py'); do
  env -i PATH=/tmp/ckvenv/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /tmp/ckvenv/bin/python "$checker"
  env -i PATH=/tmp/ckvenv/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /tmp/ckvenv/bin/python -O "$checker"
done
```

未解决：口径卡§7共12条待裁定；输入生产/接线属于后端后续任务；未做真实数据或收益验证。

提交尝试：`git add`与指定消息的`git commit`均因Git元数据只读、无法创建index.lock失败；改动保留在工作区，未push、未stash、未跳过hooks。
