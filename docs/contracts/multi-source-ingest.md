# 多源统一接入口径契约（T-A153，draft）

状态：draft，架构契约，不代表已实现。基线 main `4aae38a`。供后端 T-B143（离线导入 hsjday、gbbq、HF 1 分钟、tdx-min）使用，§3 是 T-B143 必须遵守的映射表。

依据（只引用函数名、用例名、文件路径加章节号）：
- 编排者 2026-11-14 13:44（丹佛）裁定（`rules/TEAM-RULES.md` 末节）：全部导入 hsjday、gbbq、hf-1min 2022+、tdx-min；只导 A 股；只追加、不覆盖麦蕊行；source 字段区分来源；不删原文件。
- 本单派单口径：成交量统一为股（麦蕊 v×100）；库存 adj_type 为 none，复权因子由 gbbq 统一算。
- 编排者转用户 t1120u：**以 DS 11-10 重建数据和 DS 转换脚本为口径真源**，避免两套口径。DS 脚本在 `origin/ds/T-B136` 的 `src/backend/retest/t_r58/`（`ds/B-01`、`ds/T-15-retest`、`ds/R67-gate-successor` 中 `prepare_hf.py`、`prepare_tdx.py`、`splice.py` 内容相同）。HF 转换器是团队数据区的 `hf-1min/scripts/convert.py`（`convert_file`），DS 的 `prepare_hf.main` 调的就是它，并用 `compare_manifest` 要求产物 manifest 与参考 manifest 关键字段一致。DS 数据实物在用户电脑 F: 盘，本单不读；脚本看不出的项列在 §6。
- 现有契约：`daily-bars-tdx.md`（下称日契）、`intraday-bars.md`（分契）、`daily-bars-source.md`（源契）。与它们冲突处列在 §5，裁定前现契约照旧有效。
- 麦蕊日线入库的现行字段处理在 T-B140 回填脚本 `tb140_history_load`（`validate_bar`、`market_of`、`_trade_date`、`_identity_ok`），位于 be/T-B140 工作树，**尚未合入 main**；下文引用这些函数名均指该脚本。
- 实测记录：`reports/T-DATA-SRC.md`、`reports/T-T81.md`、`reports/T-B140.md`、`reports/T003-mairui-capability.md`；研究方案 `docs/strategies/T-R58/retest_plan.md` §2.4、§2.7。
- 麦蕊官方文档（2026-11-14 抓取）：https://www.mairuiapi.com/hsdata 的「历史分时交易」「最新分时交易（Pro版）」「历史分时交易（Pro版）」「完整历史分时交易（Pro版）」。

## 1. 定位与源清单

- 日报、today、owned 快照仍只用麦蕊（日契 §1、§4；分契 §3.5）。本单只统一离线来源的入库口径和跨源规则，不改产品链路。
- T-B143 范围：hsjday / vipdoc 的 .day、.lc1、.lc5，HF 2022plus，gbbq。麦蕊日线、分钟线的映射写在 §3，只为口径对齐；麦蕊写入仍归现有入口。

| 源 | 文件 / 接口 | 目标表 | source 取值 |
| --- | --- | --- | --- |
| 麦蕊日线 | `/hsstock/history`、`/hsstock/latest`（d/n） | `market.daily_bars` | mairui |
| 麦蕊 1 分钟 | `pro/latest`、`pro/history`、`history/full`（1/n） | `market.minute_bars` | mairui |
| 通达信日线 | hsjday.zip 官方包、用户 vipdoc `lday/*.day`（同格式） | `market.daily_bars` | tdx_local |
| 通达信 1 分钟 | vipdoc `minline/*.lc1`（box 副本 tdx-min） | `market.minute_bars` | tdx_local |
| 通达信 5 分钟 | vipdoc `fzline/*.lc5` | `market.minute5_bars` | tdx_local |
| HF 1 分钟 | `hf-1min/2022plus/{SH,SZ}/*.parquet`（revision `ba589a11534825044fe5a6b84838f50ba8d8d188`） | `market.minute_bars` | **hf_1min**（新值，见 §5 C4） |
| gbbq 权息 | gbbq.zip 内 `gbbq` | 新表，见 §5 C5 | — |

- hsjday 与 vipdoc 同写 tdx_local；具体是哪个包、哪次快照，记在审计清单与 pipeline_runs（日契 §3.3 的清单机制），不再拆 source 取值。

## 2. 逐字段口径

### 2.1 代码与交易所后缀
- 库内统一为 6 位数字加 `.SH`、`.SZ`、`.BJ`（`normalize_code`）。
- 通达信：交易所取文件所在目录与文件名前缀（`scan`），不按代码段猜。HF：取 `exchange` 列，须与路径一致（`convert_file`）。麦蕊：按请求代码，响应若带代码须一致（`validate_bar`、`_identity_ok`）。
- 只按代码段推断时，用三位前缀白名单（`market_of`：沪 600/601/603/605/688/689，深 000/001/002/003/300/301/302，京 43x/83x/87x/920），未知前缀拒绝。**920 不得判成 SH**：T-B140 旧 `mkt()` 曾把 355 只 920 写成 `.SH`，已修正。
- 分钟线只收沪深上述前缀（DS `splice.selected_symbol`、`splice.selected_lc1`）。
- 北交所 920：2024-04-22 起新上市用 920；2025-10-09 存量 248 家整体切换，规则为前三位改 920、后三位不变、重复时第四位递进；新代码连续展示上市以来行情（北交所通知，经 https://www.ctsec.com/news/detail/9316731 、https://news.bjd.com.cn/2025/10/09/11342458.shtml 转载）。库里没有官方新旧对照表，所以只按当前代码入库；**旧码行不改写成 920，不并入 920 的历史**。
- 资格：沿用日契 §3.3 第 1 步，只收 `securities` 中 type 为 stock 的代码。是否放宽到退市股，见 §5 C3。

### 2.2 日期与时区
- 日线写 `trade_date`（date）。分钟写 `ts`（timestamptz），一律按 Asia/Shanghai 解释，表示 **bar 结束时刻**（`market.minute_bars` 列注释）。
- 麦蕊日线 `t`：官方示例为 `YYYY-MM-DD 00:00:00`，T-B140 实际返回 `YYYY-MM-DD`，两种都要接受，只允许时间部分为 00:00:00（`_trade_date` 目前只认后者，见 §5 C9）。
- .day：YYYYMMDD（`parse_day_bytes`、DS `data.DailyArchive.records`）。.lc1 / .lc5：年 = d 整除 2048 加 2004，月 = (d 模 2048) 整除 100，日 = (d 模 2048) 模 100；时间 = 当日零点加分钟数（`decode_lc_date`、DS `splice.decode_lc1`）。
- HF：原始 timestamp 无时区、北京时间、bar 结束时刻；2022plus 已 `tz_localize` 为 Asia/Shanghai（`convert_file`）。T-B143 直接读 2022plus，不再本地化，不再合并 09:30。
- 交易日历：按 DS `sessions.merged_calendar`。2026-08-07 及以前用 HF metadata 的 `market_calendar.csv`，之后用预公告日历 `config/trading_calendar.json`（sha256 与 DS `runner_data.CALENDAR_SHA` 一致）；两段重叠须一致，结果须等于 hsjday sh000001 的交易日集合（指数只核对，不定义日历）。库里 `market.trading_calendar` 只有 2026 年（T-T81），补历史日历见 §5 C8。

### 2.3 分钟时间戳（09:30 / 09:31、13:00）
- 统一口径：每日首根 **09:31**（含开盘集合竞价），上午 09:31–11:30，下午 13:01–15:00，每天 240 根；5 分钟首根 09:35，48 根（分契 §1.2；`retest_plan.md` §2.7 第 2–3 条）。
- HF：原始有 09:30 根，`convert_file` 已并入 09:31：open 取 09:30，high、low 取两根极值，close 取 09:31，量额相加；只有 09:30 没有 09:31 时移记为 09:31。
- .lc1：本身没有 09:30。已知异常：上午最后一根标成 13:00、缺 11:30。按 DS `splice.relabel_1300`：当日恰 240 根、除 13:00 外标签齐全，就把 13:00 改记为 11:30；否则丢掉这根 13:00；11:30 与 13:00 同时存在即拒绝。
- .lc5：DS 不读 lc5，没有同类异常的证据，不套用 13:00 规则。
- 麦蕊 1 分钟：标签是开始还是结束、有没有 09:30 根，**未验证**（分契 §1.1）。核实前不平移、不合并。

### 2.4 价格、成交量、成交额
- 库内价、量、额都是 MONEY = Numeric(20,4)（`app/db/base.py`）。
- 价格：.day 为 uint32 ÷ 100（`DAY_PRICE_DIVISOR`）。.lc1 / .lc5 为 float32 元，**不 ÷100**，按 0.01 **ROUND_HALF_UP**（DS `splice.decode_lc1`；与 main 的差异见 §5 C6）。HF 为 float64 元，DS 不另舍入，入库只量化到列精度 4 位。麦蕊原值写入。
- 成交量统一为**股**：麦蕊日线 v 是手，×100（T003 GAP2；`validate_bar`；T-T81 全库额 ÷（量 × 收）中位 1.0002）。.day、.lc1、.lc5、HF 本来就是股，不乘。麦蕊 1 分钟 v 的单位官方文档没写，**未验证**，核实前不写麦蕊分钟量。
- 成交额统一为**元**，各源原值，量化到 4 位。.day、.lc1 的 float32 只有约 7 位有效数字，4 位量化不损失信息；DS 研究不舍入是因为在 float64 里算，两者不冲突。
- 麦蕊陷阱：单股网络源 `/hsrl/ssjy/{code}` 的 v 是**万手**（T003 GAP2）；`ssjy/all` 的成交额取整到百元（T-B140）。这两个接口不作为历史入库源。
- 分钟量合计与日量本来就差几十股（通达信自身如此，T-DATA-SRC），不做「合计等于日量」的强校验（分契 §1.2）。

### 2.5 复权
- 三张行情表只存不复权原始价，日线 adj_type 为 none（日契 §2、分契 §1.1）。不读、不存任何 qfq / hfq 序列。
- 因子统一由 gbbq 算，按 DS `data.load_gbbq` 与 `retest_plan.md` §2.4：
  - 只收 category 为 1（除权除息）且 market 为 0（SZ）或 1（SH）的事件，代码按 GBK 解码；
  - 每股现金 D = 红利 ÷ 10，配股价 Pp 原值，送转比例 S = 送转 ÷ 10，配股比例 R = 配股 ÷ 10；
  - 除权（息）参考价 ref_e = (pc_raw − D + Pp × R) / (1 + S + R)，pc_raw 为除权日前一交易日的不复权收盘（沪交易规则第 4.3.2 条、深第 4.4.2 条）；
  - 交易日 t 只用除权日 e ≤ t 的事件；跨日比值用后复权因子 F_t = Π(e≤t) pc_raw,e / ref_e。
- 北交所：DS 不收 BJ 事件，所以北交所缺因子，记 `adjust_factor_missing`，不补 1（源契 §6 Q2 的保守规则不变）。
- 麦蕊 pc 已按除权除息调整（T-T81：2,797 行 pc 不等于上一日收盘，分布与除权相符），只作 ref_e 的旁证，不能当 pc_raw。
- 已知局限：gbbq 只有单一快照，事后更正无法追溯（`retest_plan.md` §2.4 第 5 条）。

### 2.6 停牌与零成交
- 麦蕊日线：sf 为 1 时写 is_suspended=true。实际返回的停牌行带平价 OHLC（四价相等，等于 pre_close），量额为 0（T-T81：1,149 行全部如此）。按源原样写入；下游 `OwnedDailyBarsReader.read` 先判 is_suspended，所以不会当成交易日用。与源契 §7 ④「占位行 OHLC 为空」冲突，见 §5 C10。
- 通达信、HF：停牌日没有记录，**不得据缺行推断停牌，不写占位行**；is_suspended 写空（日契 §2）。HF 的 `no_bar_day_classification.csv` 不转换成停牌标志。
- 零成交不等于停牌：有记录、量为 0 的分钟或日线照常写入，不设 is_suspended；单位自检跳过量为 0 的记录（`unit_suspect`）。

## 3. 后端 T-B143 必须遵守的映射表

记号：D = `market.daily_bars`，M = `market.minute_bars`，M5 = `market.minute5_bars`，E = 拟建权息事件表（§5 C5 裁定前不建、不写）。「记录拒绝」沿用日契 §3.3 的记录级拒绝（`invalid_date`、`non_finite`、`out_of_range`、高低价矛盾、价格为 0），只拒该条、计数、不置 partial；「文件拒绝」置 partial、其他文件照常。

| 源 × 源字段 | 库列 | 换算 | 精度 / 量化 | 拒绝条件 |
| --- | --- | --- | --- | --- |
| .day 文件名市场 + 6 位代码 | D.code | 目录与前缀定交易所，`normalize_code` | 6 位 + 后缀 | 非 A 股、非 stock 跳过并按原因计数（`scan`） |
| .day 日期 | D.trade_date | YYYYMMDD | date | 非法日期记录拒绝；同文件同日重复则文件拒绝（DS `DailyArchive.records` 报错） |
| .day open/high/low/close | D.open/high/low/close | uint32 ÷ 100 | 到分，无需舍入 | 价格为 0、高低价矛盾记录拒绝 |
| .day volume | D.volume | uint32，股，不乘 | 整数 | 单位自检失败文件拒绝（`unit_suspect`，额 ÷ 量落在 [low, high] ±1%，失败超过 5%） |
| .day amount | D.amount | float32，元 | 4 位 | `non_finite`、`out_of_range` 记录拒绝 |
| .day 保留字段 | 不写 | — | — | 不当前收用；D.pre_close 写空 |
| .day 其他列 | D.adj_type / source / is_suspended / source_licence_id | none / tdx_local / 空 / 空 | — | — |
| .lc1 代码 | M.code | 只收 sh、sz 目录与前缀白名单（DS `selected_lc1`） | 6 位 + 后缀 | bj 目录不读 |
| .lc1 日期 + 分钟数 | M.ts | 打包日期解码；零点加分钟数；Asia/Shanghai；13:00 按 `relabel_1300` | 结束时刻 | 非法日期、分钟数 ≥ 1440、11:30 与 13:00 同日共存、重复时间戳：文件拒绝 |
| .lc1 open/high/low/close | M.open/high/low/close | float32 元，不 ÷100 | 0.01，ROUND_HALF_UP | `non_finite`、高低价矛盾记录拒绝 |
| .lc1 volume | M.volume | uint32，股 | 整数 | 单位自检同 .day |
| .lc1 amount | M.amount | float32，元 | 4 位 | `non_finite`、`out_of_range` 记录拒绝 |
| .lc1 其他列 | M.source / source_licence_id | tdx_local / 空 | — | — |
| .lc5 各字段 | M5 同名列 | 同 .lc1，不套 13:00 规则 | 价 0.01 ROUND_HALF_UP，额 4 位 | 同 .lc1；bj 处理见 §5 C7 |
| HF symbol + exchange | M.code | symbol + `.` + exchange | 6 位 + 后缀 | `is_bj` 为真或 exchange 为 BJ：不读；前缀不在白名单：拒绝 |
| HF timestamp | M.ts | 直接用（已带 Asia/Shanghai，09:30 已并入） | 结束时刻 | 不在 09:31–11:30、13:01–15:00：文件拒绝；日期晚于 2026-08-06：不写（§4） |
| HF open/high/low/close | M.open/high/low/close | float64 元 | 4 位（只量化到列精度） | `non_finite`、高低价矛盾记录拒绝 |
| HF volume | M.volume | int64，股 | 整数 | 负值记录拒绝 |
| HF turnover | M.amount | float64，元 | 4 位 | `non_finite`、`out_of_range` 记录拒绝 |
| HF 其他列 | M.source / source_licence_id | hf_1min / 空 | — | C4 迁移前不写 |
| gbbq market + code | E.code | 0 → SZ，1 → SH；GBK 解码 | 6 位 + 后缀 | 其他 market（含北交所）、category 不为 1：跳过 |
| gbbq datetime | E.ex_date | YYYYMMDD | date | 非法日期：整包拒绝（DS 报错） |
| gbbq 红利、配股价、送转、配股 | E.cash_per_share / rights_price / bonus_ratio / rights_ratio | ÷10 / 原值 / ÷10 / ÷10（对齐 DS `sim.Event`） | 精度待 C5 | 截断、包 sha256 与清单不符：整包拒绝 |
| 麦蕊日线 t | D.trade_date | `YYYY-MM-DD` 或 `YYYY-MM-DD 00:00:00` | date | 其他格式记录拒绝 |
| 麦蕊日线 o/h/l/c、a | D 同名列 | 元，原值 | 4 位 | `validate_bar` |
| 麦蕊日线 v | D.volume | 手 × 100 | 整数股 | 换算后非整数拒绝（`validate_bar`） |
| 麦蕊日线 pc / sf | D.pre_close / is_suspended | 前收原值 / 1 为真 | — | pc 非正拒绝 |
| 麦蕊 pro/latest、pro/history 的 pc、sf | **不写** | 官方语义：pc 为涨跌幅、sf 为涨跌额，**与日线同名字段不同** | — | 禁止映射到 pre_close、is_suspended |
| 麦蕊 history/full 的 pc、sf | 不写（分钟表无此列） | 官方语义：pc 为前收、sf 为停牌标志 | — | — |
| 麦蕊 1 分钟 v、t | M.volume / ts | 单位与标签**未验证** | — | 核实前不写 |

## 4. 源优先级与冲突规则

- **日线**：mairui 优先于 tdx_local。主键 (code, trade_date, adj_type) 一键一行；通达信遇已有任何行一律 DO NOTHING，不覆盖（日契 §2）。麦蕊后到遇已有 tdx_local 行怎么办，见 §5 C1。hsjday 与 vipdoc 同键：先写者留下，差异进对账报告。
- **1 分钟**：mairui > tdx_local > hf_1min，并按 DS 拼接常量分段（`splice` 的 `HF_END`、`SINGLE_DAY`、`MAIN_START`）：
  - hf_1min 只写 2026-08-06 及以前；tdx_local 的 .lc1 只写 2026-08-07 及以后（box 上 08-07 为单日包，08-10 起为主包）；
  - **每个股票-日只取一个来源**，不跨源补根（DS `merge_sources`）；
  - mairui 与 tdx_local 的分界沿分契 §1.3（通达信截止到库里该代码最早 mairui 分钟所在日的前一开市日）。
- **5 分钟**：只有 tdx_local（.lc5），不由 1 分钟聚合写入 M5（分契 §2.2）。
- **差异比对与标记**（不新增阈值）：
  - 日线：OHLC 到分完全相等，量完全相等，额 |差| ≤ max(1 元, |已有值| × 2.4e-7)（日契 §5，`AMOUNT_ABS_TOL`、`AMOUNT_REL_TOL`）；
  - 分钟：OHLC、量完全相等，额不比（`amount_compared` 为 false；分契 §1.2）；
  - 同键已有行一律只对账、不写入；差异写入导入时的对账 jsonl（日契 §3.3「导入时的落盘文件」，字段 code、trade_date、ts、field、existing_source、existing_value、tdx_value、tolerance、kind），末行汇总。HF 复用同一格式，`tdx_value` 一列放 HF 的值、kind 照旧，来源写进 pipeline_runs。
  - 库里不加差异标记列；差异只进报告与运行汇总，不改任何已有行。
  - `retest_plan.md` §2.7 的 0.005 元、0.1%、98% 是研究门槛（98% 标「未验证」），导入只报告，不作为拒绝条件。DS `check_splice` 遇这些失败会停，T-B143 不调用它当导入闸。

## 5. 与现有契约冲突 / 待编排者裁定

| # | 现契约 / main | 本单口径与推荐 |
| --- | --- | --- |
| C1 | 日契 §3.4：通达信只导麦蕊 3 年回填起点前一开市日 D 以前，重叠期只核对；同键双方都 DO NOTHING（U-T1） | 与「全部导入」冲突。**推荐**：取消 D 截止；麦蕊后到时可替换 tdx_local 行（**只允许这一种跨源替换**，替换前把差异写对账明细）。否则 T-B140 回填尚未覆盖的约 4,380 只代码（T-T81）会被通达信先占键，快照又排除 tdx_local，日报出现缺口。备选：保留 D，麦蕊窗口内不写通达信 |
| C2 | 分契 §1.3：跨源先写者留下，没有 HF | 推荐按 §4 的 DS 日期分段和股票-日单源 |
| C3 | 分契 §2.1「全市场分钟线本期不存」；`scan` 只收 listed | 「全部导入」要求全市场。HF 2022plus 约 13.9 亿行（manifest），存量与磁盘需评估。推荐：按 DS 股票池（沪深、含退市）导入，退市股须先在 `securities` 中存在（不自动建主数据）；存储预算另报 |
| C4 | `MINUTE_BAR_SOURCES` 无 HF 取值 | 推荐新增 hf_1min（新迁移改 CHECK，downgrade 有该值时拒绝，同 0034 口径） |
| C5 | 日契 §2：复权按麦蕊 pc 推；库里没有权息表 | 推荐改为 gbbq 统一算（§2.5）；新建只存 category 1 事件的表，字段对齐 DS `sim.Event`：code、ex_date、cash_per_share、rights_price、bonus_ratio、rights_ratio、source、snapshot_sha256；列精度与 `prepare` 的 A(d) 衔接另定 |
| C6 | `tdx_local._quantize` 用 Decimal 默认上下文，即 ROUND_HALF_EVEN | 推荐向 DS 靠拢，分钟价改 ROUND_HALF_UP。只有 float32 恰好落在半分时有差别（如 10.125：HALF_EVEN 得 10.12，DS 得 10.13） |
| C7 | 分契 §1.2：分钟默认要求 bj 目录，可 `,exclude-bj` | 推荐向 DS 靠拢：.lc1 与 HF 一律不导北交所（HF 北交所对日线一致率 55–68%，T-DATA-SRC）。.lc5 北交所没有 DS 依据，推荐同样排除。日线 bj .day 照日契导入 |
| C8 | 库日历只有 2026 | 推荐按 `sessions.merged_calendar` 补 2022 起历史日历，另开单 |
| C9 | `_trade_date`（`tb140_history_load`，未合入 main）只认 `YYYY-MM-DD` 和 `YYYYMMDD` | 推荐加 `YYYY-MM-DD 00:00:00`（官方示例格式），时间部分不为零则拒绝 |
| C10 | 源契 §7 ④：停牌占位行 OHLC、量额全空 | 麦蕊实际返回平价 OHLC、零量额，库内已有 1,149 行。推荐修订源契：麦蕊停牌行按源原样写入，下游以 is_suspended 为准；不回写已有行 |
| C11 | `parse_lc_bytes` 没有 13:00 处理，会把 13:00 当合法分钟写入 | 推荐采用 `relabel_1300`（§2.3） |

## 6. 待 F: 实物核对（脚本看不出，不猜）

DS 数据在用户电脑 F:\ashare-invest-assistant\data\。下列各项须由能读 F: 的角色只读核对后回填；核对前 T-B143 以 box 数据区为输入，口径按本契约。
- [ ] `tdx-pack/hsjday.zip`、`gbbq.zip` 的完整 sha256 是否与 box `tdx-pack` 的 `hsjday_20261110.zip`、`gbbq_20261110.zip` 相同；`T-B136-tdx-manifest.json` 是否存在。DS `prepare_tdx.prepare` 不记 Last-Modified，下载时点只能从 manifest 或文件时间旁证。
- [ ] `hf-1min/T-B136-hf-ready.json` 是否存在、内容是否 ok；`2022plus/manifest.json`、`manifest_files.csv` 的 sha256 是否与 box 相同（`compare_manifest` 只保证关键字段一致，不保证字节相同）。
- [ ] `hf-1min/raw/metadata` 是否在，四个 csv（market_calendar、coverage_by_instrument、no_bar_day_classification、absent_instruments）的 sha256。box 已删 raw，只留 `source_meta/metadata`。
- [ ] `calendars` 目录实际有哪些文件；预公告日历的 sha256 是否等于 `runner_data.CALENDAR_SHA`。
- [ ] `retest-inputs` 下 st_history.csv、listing_history.csv、termination_list.csv、delisting_period.csv 的 sha256 是否与 `docs/strategies/T-R65/README.md` 产物清单一致。这些是状态数据，不进本表映射。
- [ ] DS 是否持有 tdx-min（vipdoc 1 分钟）包及其 manifest、SHA256SUMS；没有的话，DS 的 lc1 输入是什么（`runner_data.preflight` 支持两包或本地 vipdoc 两种）。

## 7. 验收（G/W/T，全部用虚构代码与数值）

后端 T-B143：
- `test_msi_day_volume_shares_not_multiplied`：Given 构造 .day，价 1234（整数）、量 700、额 8638.0 / Then 价 12.34，量 700（不乘 100），source 为 tdx_local，pre_close、is_suspended 为空。
- `test_msi_day_duplicate_date_rejects_file`：Given 同文件两条同日记录 / Then 该文件拒绝，运行为 partial，其他文件照常。
- `test_msi_lc1_price_round_half_up`：Given .lc1 价 10.125（float32 可精确表示）/ Then 写 10.13。
- `test_msi_lc1_relabel_1300`：Given 一个股票-日 239 个标准标签加 13:00 / Then 13:00 改为 11:30；Given 条件不全 / Then 丢弃 13:00；Given 11:30 与 13:00 并存 / Then 文件拒绝。
- `test_msi_lc1_bj_not_read`：Given root 下有 bj/minline / Then 不扫描、不写入，清单记缺口。
- `test_msi_hf_ts_and_source`：Given HF 产物一行 09:31+08:00 / Then M.ts 为该时刻，source 为 hf_1min；不再合并 09:30。
- `test_msi_hf_bj_and_after_cutoff_skipped`：Given HF 北交所文件、及 2026-08-07 的 HF 行 / Then 都不写。
- `test_msi_minute_one_source_per_stock_day`：Given 同一代码 2026-08-07 同时有 HF 与 .lc1 / Then 只写 tdx_local；不用另一源补缺根。
- `test_msi_existing_mairui_never_overwritten`：Given 已有 mairui 行收盘 12.00，通达信同键 12.01 / Then 原行不变，对账 jsonl 一条 mismatch，复跑 inserted 为 0。
- `test_msi_gbbq_category1_shsz_only`：Given 构造事件 category 1 的 SH、SZ 各一条，category 2 一条，北交所一条 / Then 只得两条，换算为红利 ÷10、送转 ÷10、配股 ÷10。
- `test_msi_gbbq_ref_price`：Given pc_raw 12.00、D 0.2、Pp 8.00、S 0.1、R 0.1 / Then ref_e = (12.00 − 0.2 + 0.8) / 1.2 = 10.50；除权日晚于 t 的事件不参与。
- `test_msi_mairui_pro_pc_sf_not_mapped`：Given pro/history 一行带 pc、sf / Then 不写 pre_close、is_suspended。
- `test_msi_mairui_daily_t_midnight_format`：Given t 为 `2025-04-21 00:00:00` 与 `2025-04-21` / Then 同一 trade_date；Given `2025-04-21 10:00:00` / Then 记录拒绝。
- `test_msi_no_network`：Given 打桩 `egress.mairui_get` / Then 导入全程调用 0 次。

## 8. 未验证

- 麦蕊 1 分钟 v 的单位、t 是开始还是结束、有无 09:30 根（分契 §1.1，单 D 分钟线首次实调核对）。
- 麦蕊 `/hsstock/history` 对 `.BJ` 能否返回历史；官方另有 `/bj/...` 接口族（https://www.mairuiapi.com/bjdata）。
- 北交所新旧代码对照表内容（北交所官网有，库里没有）。
- .lc5 是否也有 13:00 类异常；北交所 .lc5 质量。
- HF 上游数据权利（仓库声明 Apache-2.0，上游不明，T-DATA-SRC）。
- `retest_plan.md` §2.7 的 98% 重叠一致率。
