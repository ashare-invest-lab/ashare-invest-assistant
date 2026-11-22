# T-R105｜S-01 与 H-01 参数出处汇总

## 处理方案

本轮依据 T-R104c 的 E1–E9，只登记总表中 9 条“取值有文献”或“取值有公开研究材料／学位论文／指数编制方案”的参数。现行正式卡的机器块身份与正文哈希按同一 `key + version_no` 不可变，给卡增加正文注释也会形成同版本内容冲突。因此本轮不改以下三张卡，不自行升版：

- `docs/strategies/cards/st_pullback_ma.md`
- `docs/strategies/cards/hold_risk_monitor.md`
- `docs/strategies/T-R16/S-01_st_pullback_ma.md`

本文件承载对应参数说明与完整出处，保留现值、规则正文、参数值、生命周期和 G7。G7 保持 ☐。每条均明确 A 股有效性未验证（待复测）。

## S-01 短线·强势股回踩

### T-R16 草稿的 `rs_pct=0.8`

- **出处 E2**：John M. Griffin、Xiuqing Ji、J. Spencer Martin，《Global Momentum Strategies: A Portfolio Perspective》，公开论文 PDF，<https://www.sem.tsinghua.edu.cn/__local/D/DD/78/78AD45274C85845E7EB553A2FE4_702663DF_3A0B37.pdf?e=.pdf>，第 24 页。
- **原文取值**：按价格或盈利动量排序取前 20%赢家和后 20%输家，对应分位阈值 `0.8`。
- **差异与状态**：原文是动量排序方法，不等于本卡 20 日 A 股截面实现；现值 `0.8` 保留，差异待定。有文献采用，A 股有效性未验证（待复测）。

### T-R16 草稿的 `hard_stop_pct=0.08`

- **出处 E3**：Jia-Hao Syu、Yi-Ren Yeh、Mu-En Wu、Jan-Ming Ho，《Self-Management Portfolio System with Adaptive Association Mining: A Practical Application on Taiwan Stock Market》，公开 PDF，<https://mdpi-res.com/d_attachment/healthcare/healthcare-09-01093/article_deploy/healthcare-09-01093-v2.pdf>，第 3.2 节。
- **原文取值**：止损候选集合含 `−3%`、`−5%`、`−8%`、`−10%`，其中包含 8% 止损。
- **差异与状态**：原文为台湾市场止损候选集合，不限定本卡收盘触发和 T+1 执行；现值 `0.08` 保留，口径差异待定。有文献采用，A 股有效性未验证（待复测）。

### T-R16 草稿的 `time_stop=5`

- **出处 E4**：Zhixi Li、Vincent Tam，《A Machine Learning View on Momentum and Reversal Trading》，公开 PDF，<https://mdpi-res.com/d_attachment/algorithms/algorithms-11-00170/article_deploy/algorithms-11-00170-v2.pdf>，第 2.1 节。
- **原文取值**：持有期网格含 `5`、`10`、`15`、`20` 个交易日，采用过 5 日持有期。
- **差异与状态**：原文是持有期参数，不含本卡“满 5 日且未达 1R”的组合条件；现值 `5` 保留，组合口径差异待定。有文献采用，A 股有效性未验证（待复测）。

### 现行正式卡的 `hard_stop_pct=0.08`

- **出处 E3**：Jia-Hao Syu、Yi-Ren Yeh、Mu-En Wu、Jan-Ming Ho，《Self-Management Portfolio System with Adaptive Association Mining: A Practical Application on Taiwan Stock Market》，公开 PDF，<https://mdpi-res.com/d_attachment/healthcare/healthcare-09-01093/article_deploy/healthcare-09-01093-v2.pdf>，第 3.2 节。
- **原文取值**：止损候选集合含 `−3%`、`−5%`、`−8%`、`−10%`，其中包含 8% 止损。
- **差异与状态**：原文为台湾市场止损候选集合，本卡采用收盘止损与 T+1 执行；现值 `0.08` 保留，口径差异待定。有文献采用，A 股有效性未验证（待复测）。

### 现行正式卡的 `time_stop=5`

- **出处 E4**：Zhixi Li、Vincent Tam，《A Machine Learning View on Momentum and Reversal Trading》，公开 PDF，<https://mdpi-res.com/d_attachment/algorithms/algorithms-11-00170/article_deploy/algorithms-11-00170-v2.pdf>，第 2.1 节。
- **原文取值**：持有期网格含 `5`、`10`、`15`、`20` 个交易日，采用过 5 日持有期。
- **差异与状态**：原文不含本卡“未达 1R”的组合条件；现值 `5` 保留，组合口径差异待定。有文献采用，A 股有效性未验证（待复测）。

## H-01 持仓风险体检

### `cost_atr_k=2.0`

- **出处 E5**：Definedge Securities，《Definedge Weekly Newsletter，2020-08-20》，公开研究通讯，<https://insight.definedgesecurities.com/newsletters/year-2020/08/20-08-2020-Weekly-Newsletter.pdf>，正文示例段。
- **原文取值**：多头止损距离采用 `2×ATR20`。
- **差异与状态**：本卡现值为 `2.0×ATR14`，文献周期是 ATR20；现值 `2.0` 保留，ATR 周期差异待定。有文献采用，A 股有效性未验证（待复测）。

### `ma_long=60`

- **出处 E6**：National Taiwan University Scholars，《Research of Taiwan Stock Market Intra-day Price and Quantity Trading Strategy》，学位论文条目，<https://scholars.lib.ntu.edu.tw/entities/publication/4cc73b6c-6815-423b-b25c-08d51f3fe630>，摘要中的 Trading tactic 3。
- **原文取值**：台湾基准指数使用 `MA60` 作为买入条件。
- **差异与状态**：原文为台湾市场策略的指数买入条件，本卡用于持仓风险监控；现值 `60` 保留，市场与用途差异待定。有文献采用，A 股有效性未验证（待复测）。

### `single_cap=0.20`

- **出处 E7**：Copenhagen Business School，《Master’s Thesis in Applied Economics and Finance》，公开学位论文，<https://research-api.cbs.dk/ws/portalfiles/portal/58450455/daniel_marthendal_olsen_og_mike_kennet_eschen.pdf>，第 63 页。
- **原文取值**：单一资产限制为 `20%`，背景为丹麦养老金分散规则。
- **差异与状态**：原文资产类别与监管背景不同于本卡 A 股单只股票限额；现值 `0.20` 保留，适用背景差异待定。有文献采用，A 股有效性未验证（待复测）。

### `sector_cap=0.40`

- **出处 E8**：VanEck／Morningstar，《Quality Companies, Attractive Valuations》，Morningstar Wide Moat Focus Index 编制说明，<https://www.vaneck.com/globalassets%2F%68ome%2Fus%2Finvestments%2Fmodel-delivery%2Fmorningstar-wide-moat-sma%2Fmoat-presentation-gips.pdf>，第 23 页。
- **原文取值**：行业上限为“`40%` 或母指数对应权重 `+10%` 两者取大”，是条件上限，不是固定 40%。
- **补充参照 E9**：Securities and Exchange Board of India，《Scheme Information Document》，公开监管文件，<https://www.sebi.gov.in/sebi_data/attachdocs/jun-2018/1528259038402.pdf>，第 20 条。原文写明多数基金单一行业总暴露不得超过 `25%`，并列出有限例外。
- **差异与状态**：本卡现值为固定 `0.40`，与 E8 的条件上限不同，E9 的 25% 仅作保守公开参照；现值 `0.40` 保留，条件上限及适用法规差异待定。有文献采用，A 股有效性未验证（待复测）。

## 范围说明

本汇总只覆盖上述 9 条。T-R104c 总表中其余 15 条参数不改、不补出处、不改变参数值或规则。E1 及其他未对应上述 9 条取值的材料不扩展为本轮参数依据。
