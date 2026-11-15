# 多源统一接入口径契约（T-A153，定稿）

状态：定稿（编排者 2026-11-14 14:31 丹佛裁定，§5），架构契约，不代表已实现。基线 main `4aae38a`。供后端 T-B143 使用：日线与 gbbq 入库，离线历史分钟线（HF、tdx-min）只登记文件目录、不入 PG。§3 是 T-B143 必须遵守的映射表，§6 是 T-B143 第一步必做核对清单。

依据（只引用函数名、用例名、文件路径加章节号）：
- 编排者 2026-11-14 13:44（丹佛）裁定（`rules/TEAM-RULES.md` 末节）：全部导入 hsjday、gbbq、hf-1min 2022+、tdx-min；只导 A 股；只追加、不覆盖麦蕊行；source 字段区分来源；不删原文件。其中分钟线落点、麦蕊替换 tdx_local 已由 14:31 裁定改写（§5 C1、C3）。
- 本单派单口径：成交量统一为股（麦蕊 v×100）；库存 adj_type 为 none，复权因子由 gbbq 统一算。
- 编排者转用户 t1120u：**以 DS 11-10 重建数据和 DS 转换脚本为口径真源**，避免两套口径。DS 脚本在 `origin/ds/T-B136` 的 `src/backend/retest/t_r58/`（`ds/B-01`、`ds/T-15-retest`、`ds/R67-gate-successor` 中 `prepare_hf.py`、`prepare_tdx.py`、`splice.py` 内容相同）。HF 转换器是团队数据区的 `hf-1min/scripts/convert.py`（`convert_file`），DS 的 `prepare_hf.main` 调的就是它，并用 `compare_manifest` 要求产物 manifest 与参考 manifest 关键字段一致。DS 数据实物在用户电脑 F: 盘，架构未读；脚本看不出的项由 T-B143 第一步核对（§6）。
- 现有契约：`daily-bars-tdx.md`（下称日契）、`intraday-bars.md`（分契）、`daily-bars-source.md`（源契）。与它们冲突处按 §5 裁定执行，三份契约的对应条款已同步加 T-A153 注记。
- 麦蕊日线入库的现行字段处理在 T-B140 回填脚本 `tb140_history_load`（`validate_bar`、`market_of`、`_trade_date`、`_identity_ok`），位于 be/T-B140 工作树，**尚未合入 main**；下文引用这些函数名均指该脚本。
- 实测记录：`reports/T-DATA-SRC.md`、`reports/T-T81.md`、`reports/T-B140.md`、`reports/T003-mairui-capability.md`；研究方案 `docs/strategies/T-R58/retest_plan.md` §2.4、§2.7。
- 麦蕊官方文档（2026-11-14 抓取）：https://www.mairuiapi.com/hsdata 的「历史分时交易」「最新分时交易（Pro版）」「历史分时交易（Pro版）」「完整历史分时交易（Pro版）」。

## 1. 定位与源清单

- 日报、today、owned 快照仍只用麦蕊（日契 §1、§4；分契 §3.5）。本单只统一离线来源的口径和跨源规则，不改产品链路。
- **分钟线不入 PG（§5 C3）**：HF 与 tdx-min 的离线历史分钟线保留为用户电脑 F: 上的 parquet（含退市股，北交所不导），PG 里只建目录表指向文件（§3.3）；分钟线读取方在本地读 parquet，不经过 PG。麦蕊盘中 1 分钟仍按分契 §1.1、§1.3 写 `market.minute_bars`，不受本条影响。
- T-B143 范围：hsjday / vipdoc 的 .day 与 gbbq 入库；.lc1、.lc5、HF 按 §3.2 文件层口径落 parquet 并登记目录表。麦蕊日线、分钟线的映射写在 §3.1，只为口径对齐，写入仍归现有入口。

| 源 | 文件 / 接口 | 落点 | 来源取值 |
| --- | --- | --- | --- |
| 麦蕊日线 | `/hsstock/history`、`/hsstock/latest`（d/n） | `market.daily_bars` | mairui |
| 麦蕊盘中 1 分钟 | `pro/latest`、`pro/history`（1/n） | `market.minute_bars`（分契） | mairui |
| 通达信日线 | hsjday.zip 官方包、用户 vipdoc `lday/*.day`（同格式） | `market.daily_bars` | tdx_local |
| gbbq 权息 | gbbq.zip 内 `gbbq` | 新表 `market.ex_rights_events`（§3.4） | tdx_gbbq |
| 通达信 1 / 5 分钟 | vipdoc `minline/*.lc1`、`fzline/*.lc5` | F: 上 parquet + 目录表 | tdx_local |
| HF 1 分钟 | `hf-1min/2022plus/{SH,SZ}/*.parquet`（revision `ba589a11534825044fe5a6b84838f50ba8d8d188`） | F: 上 parquet + 目录表 | hf_1min（只用于目录表，§5 C4） |

- hsjday 与 vipdoc 同写 tdx_local；具体包与快照记在审计清单与 pipeline_runs（日契 §3.3 的清单机制）。

## 2. 逐字段口径

### 2.1 代码与交易所后缀
- 库内统一为 6 位数字加 `.SH`、`.SZ`、`.BJ`（`normalize_code`）。
- 通达信：交易所取文件所在目录与文件名前缀（`scan`），不按代码段猜。HF：取 `exchange` 列，须与路径一致（`convert_file`）。麦蕊：按请求代码，响应若带代码须一致（`validate_bar`、`_identity_ok`）。
- 只按代码段推断时，用三位前缀白名单（`market_of`：沪 600/601/603/605/688/689，深 000/001/002/003/300/301/302，京 43x/83x/87x/920），未知前缀拒绝。**920 不得判成 SH**：T-R72 `code.md` §5 转述历史报告称 355 只错后缀已改为 `.BJ`，当前库状态未验证；基线 `7285e88` 的旧 `tb140_daily_bars.mkt()` 仍误判 920 为 SH，新回填器 `market_of()` 已判 BJ，不能笼统称「已修正」。
- 北交所历史路由、单一市场映射及错后缀修正批准关口见 [daily-bars-source.md](daily-bars-source.md) §10（T-A157 定稿；§10.7 已由 T-A157b 据 T-B146c 更新；回填跳过 43/83/87，记「旧码不请求」）。
- 分钟线只收沪深上述前缀（DS `splice.selected_symbol`、`splice.selected_lc1`）。
- 北交所 920：2024-04-22 起新上市用 920；2025-10-09 存量 248 家整体切换，规则为前三位改 920、后三位不变、重复时第四位递进；新代码连续展示上市以来行情（北交所通知，经 https://www.ctsec.com/news/detail/9316731 、https://news.bjd.com.cn/2025/10/09/11342458.shtml 转载）。库里没有官方新旧对照表，所以只按当前代码入库；**旧码行不改写成 920，不并入 920 的历史**。
- 资格：沿用日契 §3.3 第 1 步，只收 `securities` 中 type 为 stock 的代码。分钟线文件层含退市股（§5 C3）；日线入库仍按此资格。

### 2.2 日期与时区
- 日线写 `trade_date`（date）。分钟（PG 的 `ts` 与 parquet 的 `timestamp`）一律按 Asia/Shanghai 解释，表示 **bar 结束时刻**（`market.minute_bars` 列注释、DS `splice.SCHEMA`）。
- 麦蕊日线 `t`：官方示例为 `YYYY-MM-DD 00:00:00`，T-B140 实际返回 `YYYY-MM-DD`，两种都要接受，只允许时间部分为 00:00:00（`_trade_date` 目前只认后者，按 §5 C9 补）。
- .day：YYYYMMDD（`parse_day_bytes`、DS `data.DailyArchive.records`）。.lc1 / .lc5：年 = d 整除 2048 加 2004，月 = (d 模 2048) 整除 100，日 = (d 模 2048) 模 100；时间 = 当日零点加分钟数（`decode_lc_date`、DS `splice.decode_lc1`）。
- HF：原始 timestamp 无时区、北京时间、bar 结束时刻；2022plus 已 `tz_localize` 为 Asia/Shanghai（`convert_file`）。T-B143 直接读 2022plus，不再本地化，不再合并 09:30。
- 交易日历：按 DS `sessions.merged_calendar`。2026-08-07 及以前用 HF metadata 的 `market_calendar.csv`，之后用预公告日历 `config/trading_calendar.json`（sha256 与 DS `runner_data.CALENDAR_SHA` 一致）；两段重叠须一致，结果须等于 hsjday sh000001 的交易日集合（指数只核对，不定义日历）。库里 `market.trading_calendar` 只有 2026 年（T-T81），补历史日历按 §5 C8 另开单。

### 2.3 分钟时间戳（09:30 / 09:31、13:00）
- 统一口径：每日首根 **09:31**（含开盘集合竞价），上午 09:31–11:30，下午 13:01–15:00，每天 240 根；5 分钟首根 09:35，48 根（分契 §1.2；`retest_plan.md` §2.7 第 2–3 条）。
- HF：原始有 09:30 根，`convert_file` 已并入 09:31：open 取 09:30，high、low 取两根极值，close 取 09:31，量额相加；只有 09:30 没有 09:31 时移记为 09:31。
- .lc1：本身没有 09:30。已知异常：上午最后一根标成 13:00、缺 11:30。按 DS `splice.relabel_1300`：当日恰 240 根、除 13:00 外标签齐全，就把 13:00 改记为 11:30；否则丢掉这根 13:00；11:30 与 13:00 同时存在即拒绝。
- .lc5：DS 不读 lc5，没有同类异常的证据，不套用 13:00 规则。
- 麦蕊 1 分钟：标签是开始还是结束、有没有 09:30 根，**未验证**（分契 §1.1）。核实前不平移、不合并。

### 2.4 价格、成交量、成交额
- BJ 写库准入统一以 [daily-bars-source.md](daily-bars-source.md) §10（T-A172）为准；本节单位换算不构成放行。
- 库内价、量、额都是 MONEY = Numeric(20,4)（`app/db/base.py`）。
- 价格：.day 为 uint32 ÷ 100（`DAY_PRICE_DIVISOR`）。.lc1 / .lc5 为 float32 元，**不 ÷100**，按 0.01 **ROUND_HALF_UP**（DS `splice.decode_lc1`；按 §5 C6，main 的 ROUND_HALF_EVEN 不用于分钟价）。HF 为 float64 元，DS 不另舍入，parquet 原值保存。麦蕊原值写入。
- 成交量统一为**股**：麦蕊日线 v 是手，×100（T003 GAP2；`validate_bar`；T-T81 全库额 ÷（量 × 收）中位 1.0002）。.day、.lc1、.lc5、HF 本来就是股，不乘。麦蕊 1 分钟 v 的单位官方文档没写，**未验证**，核实前不写麦蕊分钟量。
- 北交所 `/bj/history` 日线 v 同样为手，入库复用 `validate_bar` 的 `VOL_MULT` 同样 ×100 换成股，价额按元原值，换算后允许写库（`reports/T-B146c.md`，小样本 1 只 920682.BJ、1 日 2026-11-13；详见 [daily-bars-source.md](daily-bars-source.md) §10.7 第 4 项；虚构夹具用例见同契约 §10.6 的 `test_ta157_bj_volume_lots_to_shares`）。真实执行仍须既有任务授权。
- 成交额统一为**元**，各源原值；入库（日线）按 MONEY 列量化到 4 位（日契 §3.3），万分之一元以下的 float32 尾数会被舍去，对元级成交额无实际影响；分钟 parquet 不舍入，同 DS。
- 麦蕊陷阱：单股网络源 `/hsrl/ssjy/{code}` 的 v 是**万手**（T003 GAP2）；`ssjy/all` 的成交额取整到百元（T-B140）。这两个接口不作为历史入库源。
- 分钟量合计与日量本来就差几十股（通达信自身如此，T-DATA-SRC），不做「合计等于日量」的强校验（分契 §1.2）。

### 2.5 复权
- 三张行情表只存不复权原始价，日线 adj_type 为 none（日契 §2、分契 §1.1）。不读、不存任何 qfq / hfq 序列。
- 因子统一由 gbbq 算，按 DS `data.load_gbbq` 与 `retest_plan.md` §2.4：
  - 只收 category 为 1（除权除息）且 market 为 0（SZ）或 1（SH）的事件，代码按 GBK 解码；
  - 每股现金 D = 红利 ÷ 10，配股价 Pp 原值，送转比例 S = 送转 ÷ 10，配股比例 R = 配股 ÷ 10；
  - 除权（息）参考价 ref_e = (pc_raw − D + Pp × R) / (1 + S + R)，pc_raw 为除权日前一交易日的不复权收盘（沪交易规则第 4.3.2 条、深第 4.4.2 条）；
  - 交易日 t 只用除权日 e ≤ t 的事件；跨日比值用后复权因子 F_t = Π(e≤t) pc_raw,e / ref_e，最早交易日因子为 1（标准后复权连乘，本契约约定，DS 与 retest_plan 未写此式，「未验证」）。
  - 一次计算只用一个 gbbq 快照（显式指定 snapshot_sha256，记入结果），不得混用多个快照的事件。
  - pc_raw 取不到（除权日前无不复权收盘，如历史起点之前或长期停牌缺行）或 ref_e ≤ 0 时，该事件不参与，记 `adjust_factor_missing:<除权日>`，不补 1、不跳过后续事件的记录。
- 北交所：DS 不收 BJ 事件，所以北交所缺因子，记 `adjust_factor_missing`，不补 1（源契 §6 Q2 的保守规则不变）。
- 麦蕊 pc 已按除权除息调整（T-T81：2,797 行 pc 不等于上一日收盘，分布与除权相符），只作 ref_e 的旁证，不能当 pc_raw。
- 已知局限：gbbq 只有单一快照，事后更正无法追溯（`retest_plan.md` §2.4 第 5 条）。

### 2.6 停牌与零成交
- 麦蕊日线：sf 为 1 时写 is_suspended=true。实际返回的停牌行带平价 OHLC（四价相等，等于 pre_close），量额为 0（T-T81：1,149 行全部如此）。按源原样写入；下游 `OwnedDailyBarsReader.read` 先判 is_suspended，所以不会当成交易日用。源契 §7 ④「占位行 OHLC 为空」不适用于麦蕊源原样行（§5 C10）。
- 通达信、HF：停牌日没有记录，**不得据缺行推断停牌，不写占位行**；is_suspended 写空（日契 §2）。HF 的 `no_bar_day_classification.csv` 不转换成停牌标志。
- 零成交不等于停牌：有记录、量为 0 的分钟或日线照常写入，不设 is_suspended；单位自检跳过量为 0 的记录（`unit_suspect`）。

## 3. 后端 T-B143 必须遵守的映射表

「记录拒绝」沿用日契 §3.3 的记录级拒绝（`invalid_date`、`non_finite`、`out_of_range`、高低价矛盾、价格为 0），只拒该条、计数、不置 partial；「文件拒绝」置 partial，其他文件照常。

### 3.1 入库：日线（`market.daily_bars`，记 D）

BJ 日线映射后的写库确认及入口约束见 [daily-bars-source.md](daily-bars-source.md) §10（T-A172），本表不单独授予放行。

| 源 × 源字段 | 库列 | 换算 | 精度 / 量化 | 拒绝条件 |
| --- | --- | --- | --- | --- |
| .day 文件名市场 + 6 位代码 | D.code | 目录与前缀定交易所，`normalize_code` | 6 位 + 后缀 | 非 A 股、非 stock 跳过并按原因计数（`scan`） |
| .day 日期 | D.trade_date | YYYYMMDD | date | 非法日期记录拒绝；同文件同日重复则文件拒绝（DS `DailyArchive.records` 报错） |
| .day open/high/low/close | D.open/high/low/close | uint32 ÷ 100 | 到分，无需舍入 | 价格为 0、高低价矛盾记录拒绝 |
| .day volume | D.volume | uint32，股，不乘 | 整数 | 单位自检失败文件拒绝（`unit_suspect`，额 ÷ 量落在 [low, high] ±1%，失败超过 5%；阈值沿用日契 §3.3） |
| .day amount | D.amount | float32，元 | 4 位 | `non_finite`、`out_of_range` 记录拒绝 |
| .day 保留字段 | 不写 | — | — | 不当前收用；D.pre_close 写空 |
| .day 其他列 | D.adj_type / source / is_suspended / source_licence_id | none / tdx_local / 空 / 空 | — | — |
| 麦蕊日线 t | D.trade_date | `YYYY-MM-DD`、`YYYYMMDD` 或 `YYYY-MM-DD 00:00:00`（C9） | date | 其他格式、时间部分非零：记录拒绝 |
| 麦蕊日线 o/h/l/c、a | D 同名列 | 元，原值 | 4 位 | `validate_bar` |
| 麦蕊日线 v | D.volume | 手 × 100 | 整数股 | 换算后非整数拒绝（`validate_bar`） |
| 麦蕊日线 pc / sf | D.pre_close / is_suspended | 前收原值 / 1 为真；停牌行平价 OHLC、零量额原样写（C10） | — | pc 非正拒绝 |
| 麦蕊 pro/latest、pro/history 的 pc、sf | **不写** | 官方语义：pc 为涨跌幅、sf 为涨跌额，**与日线同名字段不同** | — | 禁止映射到 pre_close、is_suspended |
| 麦蕊 history/full 的 pc、sf | 不写 | 官方语义：pc 为前收、sf 为停牌标志 | — | — |
| 麦蕊 1 分钟 v、t | `market.minute_bars`（分契） | 单位与标签**未验证** | — | 核实前不写 |

### 3.2 文件层口径：离线历史分钟线（parquet，不入 PG）

- 每只代码一个 parquet，列与 DS `splice.SCHEMA` 一致：symbol、exchange、timestamp（timestamp[us, tz=Asia/Shanghai]，bar 结束时刻）、open、high、low、close、volume、turnover（均 float64）、is_bj（恒为假）。
- HF：直接使用 `convert_file` 的 2022plus 产物，不再转换。.lc1 / .lc5：按下表转换后写 parquet，原文件只读不改。

| 源 × 源字段 | parquet 列 | 换算 | 精度 / 量化 | 拒绝条件 |
| --- | --- | --- | --- | --- |
| .lc1 / .lc5 代码 | symbol、exchange | 只收 sh、sz 目录与前缀白名单（DS `selected_lc1`、`selected_symbol`） | 6 位 | bj 目录不读（C7） |
| .lc1 / .lc5 日期 + 分钟数 | timestamp | 打包日期解码；零点加分钟数；Asia/Shanghai；.lc1 的 13:00 按 `relabel_1300`（C11），.lc5 不套 | 结束时刻 | 非法日期、分钟数 ≥ 1440、非法标签、重复时间戳、11:30 与 13:00 同日并存：文件拒绝 |
| .lc1 / .lc5 open/high/low/close | open/high/low/close | float32 元，不 ÷100 | 0.01，ROUND_HALF_UP（C6） | `non_finite`、高低价矛盾：记录拒绝 |
| .lc1 / .lc5 volume | volume | uint32，股，不乘 | 整数 | 单位自检同 .day（阈值用于分钟的适用性「未验证」，沿用分契 §1.2 的现行做法） |
| .lc1 / .lc5 amount | turnover | float32，元 | 不舍入（DS `decode_lc1`） | `non_finite`：记录拒绝 |
| HF symbol + exchange | symbol、exchange | 原值 | 6 位 | `is_bj` 为真或 exchange 为 BJ：不登记；前缀不在白名单：拒绝 |
| HF timestamp | timestamp | 原值（已带时区，09:30 已并入 09:31） | 结束时刻 | 不在 09:31–11:30、13:01–15:00：文件拒绝 |
| HF OHLC、volume、turnover | 同名列 | 元 / 股 / 元，原值 | 不舍入 | — |

- 单源分段照旧（§4）：hf_1min 只用 2026-08-06 及以前，tdx_local .lc1 只用 2026-08-07 及以后，每个股票-日只取一个来源；.lc5 不分段。分段写在目录表 `splice_segment`，读取方按有效区间（§3.3）选文件、过滤行，不跨源补根。

### 3.3 目录表（`market.minute_file_catalog`，新建）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| source | text | hf_1min 或 tdx_local |
| code | text | 6 位 + 后缀 |
| kind | text | 1m 或 5m |
| date_from、date_to | date | 文件内实际首末交易日（北京时间），不按分段裁剪 |
| rel_path | text | 相对配置根目录的路径，一律用正斜杠存储 |
| sha256 | text | 文件 sha256 |
| row_count | bigint | 行数 |
| splice_segment | text | 该文件可用的日期段：hf_1m（≤ `HF_END` 2026-08-06）、vipdoc_1m（≥ `SINGLE_DAY` 2026-08-07，含单日段与 `MAIN_START` 起主段）、lc5（.lc5 全部日期，无拼接）之一，取自 DS `splice` 常量 |
| generator | text | 生成脚本名与版本（文件 sha256 或提交号），如 `convert_file` 所在 convert.py、T-B143 转换脚本 |
| registered_at | timestamptz | 登记时间 |

- 主键 (source, code, kind, rel_path)；同键重复登记时 sha256 不同即拒绝并报告，不覆盖。
- **有效区间** = [date_from, date_to] ∩ splice_segment 的日期段。登记时检查同一 (code, kind) 已登记条目的有效区间，有交集即拒绝登记并报告；由此保证每个股票-日、每种 kind 只有一个文件、一个来源。文件不裁剪（HF 产物直接使用，其中晚于 `HF_END` 的行由读取方按有效区间过滤）。
- 根目录是部署参数（运维写在部署机本地 env 文件），**不写进代码常量，也不写进 compose 默认值**（同日契 §3.2）。根目录是**读取方所在主机**上的路径：在用户 Windows 上直接读时可为带盘符的路径，在 Linux 容器里读时是 F: 的挂载点（挂载由部署配置，不在本契约）。拼接规则：rel_path 按正斜杠拆段后接到根目录；rel_path 不得是绝对路径、不得含盘符或 `..`。
- 读取方打开文件前核对 sha256 与 row_count，不一致即停并报告。
- 目录表不存行情数值；删除或移动 F: 上的文件须另经用户同意（硬红线：不删用户数据）。
- 本节列名、主键、有效区间规则、`splice_segment` 取值是本契约约定，无外部出处（「未验证」，T-B143 实现时可提修改，经架构评审）。

### 3.4 入库：gbbq（`market.ex_rights_events`，新建）

| 源字段 | 库列 | 换算 | 拒绝条件 |
| --- | --- | --- | --- |
| market + code | code | 0 → SZ，1 → SH；GBK 解码 | 其他 market（含北交所）、category 不为 1：跳过 |
| datetime | ex_date | YYYYMMDD | 非法日期：整包拒绝（DS 报错） |
| 红利、配股价、送转、配股 | cash_per_share、rights_price、bonus_ratio、rights_ratio | ÷10 / 原值 / ÷10 / ÷10（对齐 DS `sim.Event`） | 截断、包 sha256 与清单不符：整包拒绝 |
| — | source、snapshot_sha256 | tdx_gbbq；gbbq.zip 的 sha256 | — |

- 主键 (code, ex_date, snapshot_sha256)：每个快照整份保留，不覆盖旧快照（gbbq 无版本，事后更正只能靠快照对比发现）。
- 四个数值列用 Numeric(20,6)。6 位小数是本契约约定（每股红利 ÷10 后最多比原值多一位），「未验证」。

## 4. 源优先级与冲突规则

- **日线**：mairui 优先于 tdx_local。主键 (code, trade_date, adj_type) 一键一行。
  - 通达信导入遇已有任何行一律 DO NOTHING，不覆盖（日契 §2）；hsjday 与 vipdoc 同键，先写者留下，差异进对账报告。
  - **麦蕊后到、已有行为 tdx_local**：麦蕊替换该行（C1）。**这是唯一允许的跨源替换**。已有行为 mairui、fake 或其他来源时，仍是 DO NOTHING。顺序：
    1. 按日契 §5 规则比对，把每个差异字段写进对账 jsonl 并落盘（kind 为 replaced_tdx_local，existing_source 为 tdx_local、existing_value 为旧值，incoming_source 为 mairui、incoming_value 为新值）；各字段都相同时也写一行（field 为 `*`，kind 为 replaced_tdx_local_same），保证每次替换都有记录。落盘失败则不替换。
    2. 执行条件更新：只在该行 source 仍为 tdx_local 时更新整行（含 source 改为 mairui），条件不满足（被并发写入改掉）则影响 0 行、不替换。
    3. 事务结束后再写一行结果（kind 为 replace_result，值为 committed、skipped 或 rolled_back），对账以结果行为准；只有第 1 步、没有 committed 结果行的，视为未替换。
    4. `UpsertStats` 增加 replaced 计数；替换不计入 conflicts，也不产生 conflict issue。
  - 不设截止日 D（C1，日契 §3.4 已改）：通达信可导全部历史；快照仍排除 tdx_local（日契 §4），日报只用麦蕊。
- **1 分钟（文件层）**：hf_1min 与 tdx_local 按 DS 拼接常量分段（`splice` 的 `HF_END`、`SINGLE_DAY`、`MAIN_START`），每个股票-日只取一个来源，不跨源补根（DS `merge_sources`）。麦蕊盘中 1 分钟在 PG，按分契 §1.3。
- **5 分钟**：只有 tdx_local（.lc5 parquet）。
- **差异比对与标记**（不新增阈值）：
  - 日线：OHLC 到分完全相等，量完全相等，额 |差| ≤ max(1 元, |已有值| × 2.4e-7)（日契 §5，`AMOUNT_ABS_TOL`、`AMOUNT_REL_TOL`）；
  - 分钟：OHLC、量完全相等，额不比（分契 §1.2）；
  - 差异写入对账 jsonl（日契 §3.3「导入时的落盘文件」，字段 code、trade_date、ts、field、existing_source、existing_value、tdx_value、tolerance、kind；替换场景另用 incoming_source、incoming_value，见上），末行汇总；库里不加差异标记列。
  - `retest_plan.md` §2.7 的 0.005 元、0.1%、98% 是研究门槛（98% 标「未验证」），导入只报告，不作拒绝条件；T-B143 不调用 DS `check_splice` 当导入闸。

## 5. 裁定（2026-11-14 编排者）

编排者 2026-11-14 14:31（丹佛）裁定，已落实到本契约与相关契约。

| # | 原契约 / main | 裁定 |
| --- | --- | --- |
| C1 | 日契 §3.4 截止日 D；同键双方 DO NOTHING（U-T1） | 取消截止日 D；麦蕊后到可替换 tdx_local 行，唯一跨源替换，先写对账明细（§4）。日契 §1、§2、§3.3、§3.4、§7 U-T1、源契 §7 ⑤ 与 §8.3、快照契约（`daily-snapshot-from-bars.md`）§13 已加 T-A153 注记 |
| C2 | 分契 §1.3 跨源先写者留下 | 离线历史分钟按 DS 日期分段、股票-日单源（§4） |
| C3 | 分契 §2.1、§2.2 分钟线入 `minute_bars` / `minute5_bars` | 离线历史分钟线不入 PG：F: 上 parquet（含退市股，北交所不导）+ 目录表（§3.2、§3.3）；日线与 gbbq 入库；读取方本地读 parquet。分契 §1.2、§2.2、§3.4 与验收已加注记 |
| C4 | `MINUTE_BAR_SOURCES` 无 HF | 因 C3，不再改 minute_bars 的 CHECK；hf_1min 只作目录表 source 取值 |
| C5 | 日契 §2 由麦蕊 pc 推因子；库无权息表 | gbbq 统一算（§2.5）；新建 `market.ex_rights_events`（§3.4）；gbbq 因子实现落地前，日契 §2、源契 §6 Q2、快照契约 §2 的缺口口径照旧 |
| C6 | `tdx_local._quantize` 为 ROUND_HALF_EVEN | 分钟价按 DS 用 ROUND_HALF_UP（只在半分边界有差，如 10.125 → 10.13） |
| C7 | 分契 §1.2 分钟默认要求 bj、可 `,exclude-bj` | .lc1、.lc5、HF 都不导北交所；日线 bj .day 照日契导入 |
| C8 | 库日历只有 2026 | 按 `sessions.merged_calendar` 补 2022 起历史日历，另开单 |
| C9 | `_trade_date`（`tb140_history_load`，未合入 main）只认 `YYYY-MM-DD`、`YYYYMMDD` | 保留这两种，加认 `YYYY-MM-DD 00:00:00`，时间部分非零拒绝 |
| C10 | 源契 §7 ④ 停牌占位行 OHLC、量额全空 | 麦蕊停牌行按源原样写（平价 OHLC、零量额），下游以 is_suspended 为准；不回写已有行 |
| C11 | `parse_lc_bytes` 无 13:00 处理 | 采用 DS `relabel_1300`（§2.3） |

## 6. T-B143 第一步必做核对清单

DS 数据在用户电脑 F:\ashare-invest-assistant\data\。T-B143 开工第一步由本团队后端**只读**核对下列各项，结果写进 T-B143 报告；任何一项与预期不一致或缺失，停下上报编排者，不自行调整口径。不改、不删 F: 上任何文件。
- [ ] `tdx-pack/hsjday.zip`、`gbbq.zip` 的完整 sha256 是否与 box `tdx-pack` 的 `hsjday_20261110.zip`、`gbbq_20261110.zip` 相同；`T-B136-tdx-manifest.json` 是否存在。DS `prepare_tdx.prepare` 不记 Last-Modified，下载时点只能从 manifest 或文件时间旁证。
- [ ] `hf-1min/T-B136-hf-ready.json` 是否存在、内容是否 ok；`2022plus/manifest.json`、`manifest_files.csv` 是否与 box 版本按 `prepare_hf.compare_manifest` 的口径语义一致（不一致才停）；字节 sha256 是否相同只记录，不作停止条件（Arrow 序列化可不同）。
- [ ] `hf-1min/raw/metadata` 是否在，四个 csv（market_calendar、coverage_by_instrument、no_bar_day_classification、absent_instruments）的 sha256。
- [ ] `calendars` 目录实际有哪些文件；预公告日历的 sha256 是否等于 `runner_data.CALENDAR_SHA`。
- [ ] `retest-inputs` 下 st_history.csv、listing_history.csv、termination_list.csv、delisting_period.csv 的 sha256 是否与 `docs/strategies/T-R65/README.md` 产物清单一致（状态数据，不进本表映射）。
- [ ] DS 是否持有 tdx-min（vipdoc 1 分钟）包及其 manifest、SHA256SUMS；没有的话，DS 的 lc1 输入是什么（`runner_data.preflight` 支持两包或本地 vipdoc 两种）。
- [ ] F: 上 2022plus 的北交所文件数（DS 配置记为 `bj_files`）与是否含退市股（manifest 的 `delisted_stocks`）：只记录。北交所文件可以存在，T-B143 不登记（C7）；退市股缺失才停。

## 7. 验收（G/W/T，全部用虚构代码与数值）

后端 T-B143：
- `test_msi_day_volume_shares_not_multiplied`：Given 构造 .day，价 1234（整数）、量 700、额 8638.0 / Then 价 12.34，量 700（不乘 100），source 为 tdx_local，pre_close、is_suspended 为空。
- `test_msi_day_duplicate_date_rejects_file`：Given 同文件两条同日记录 / Then 该文件拒绝，运行为 partial，其他文件照常。
- `test_msi_day_no_until_cutoff`：Given .day 含麦蕊 3 年窗口内的日期，未传截止日 / Then 照常导入（C1）。
- `test_msi_mairui_replaces_tdx_local_after_reconcile`：Given 已有 tdx_local 行收盘 12.00，麦蕊同键收盘 12.01 / When 麦蕊写入 / Then jsonl 先有 replaced_tdx_local 行（existing_value 12.00、incoming_value 12.01），后有 replace_result 为 committed，该行为麦蕊值且 source 为 mairui，replaced 计 1、conflicts 计 0；Given 各字段相同 / Then 有 replaced_tdx_local_same 行且仍替换；Given 打桩让 jsonl 落盘失败 / Then 不替换；Given 更新前该行已被改为 mairui / Then 影响 0 行，结果行为 skipped。
- `test_msi_existing_mairui_never_overwritten`：Given 已有 mairui 行收盘 12.00，通达信同键 12.01 / Then 原行不变，对账 jsonl 一条 mismatch，复跑 inserted 为 0。
- `test_msi_lc1_price_round_half_up`：Given .lc1 价 10.125（float32 可精确表示）/ Then parquet 中为 10.13。
- `test_msi_lc1_relabel_1300`：Given 一个股票-日 239 个标准标签加 13:00 / Then 13:00 改为 11:30；条件不全 / Then 丢弃 13:00；11:30 与 13:00 并存 / Then 文件拒绝。
- `test_msi_lc_bj_not_read`：Given root 下有 bj/minline、bj/fzline / Then 不扫描、不生成 parquet、不登记目录。
- `test_msi_minute_not_written_to_pg`：Given 打桩记录全部 SQL / When 一次离线分钟导入 / Then 对 `market.minute_bars`、`market.minute5_bars` 的 INSERT、UPDATE、DELETE 语句为 0，目录表新增对应条目。
- `test_msi_catalog_rel_path_and_root`：Given 根目录 `F:\\data`（按 Windows 路径规则）与 `/mnt/f/data`（按 POSIX 路径规则）各一，rel_path `hf/SH/600000.parquet`（虚构）/ Then 两种拼接结果分别为对应主机上的正确路径；rel_path 为绝对路径、含盘符或 `..` / Then 拒绝登记。
- `test_msi_catalog_sha_mismatch_refused`：Given 同键重复登记且 sha256 不同 / Then 拒绝并报告，原条目不变；读取时文件 sha256 与目录不符 / Then 停。
- `test_msi_catalog_one_source_per_stock_day`：Given HF 文件 date_to 为 2026-08-07（splice_segment hf_1m）与 .lc1 文件 date_from 为 2026-08-07（vipdoc_1m）/ Then 两者都可登记，有效区间分别止于 08-06、起于 08-07，读取 08-07 只返回 tdx_local；Given 再登记一个同代码 vipdoc_1m 文件覆盖 08-07 / Then 拒绝登记。
- `test_msi_gbbq_category1_shsz_only`：Given 构造事件 category 1 的 SH、SZ 各一条，category 2 一条，北交所一条 / Then 只入库两条，换算为红利 ÷10、送转 ÷10、配股 ÷10，source 为 tdx_gbbq。
- `test_msi_gbbq_one_snapshot_and_missing_pc`：Given 两个快照含同一事件 / Then 指定一个快照计算时该事件只乘一次；Given 除权日前无收盘 / Then 记 adjust_factor_missing，不补 1。
- `test_msi_gbbq_ref_price`：Given pc_raw 12.00、D 0.2、Pp 8.00、S 0.1、R 0.1 / Then ref_e = (12.00 − 0.2 + 0.8) / 1.2 = 10.50；除权日晚于 t 的事件不参与。
- `test_msi_mairui_pro_pc_sf_not_mapped`：Given pro/history 一行带 pc、sf / Then 不写 pre_close、is_suspended。
- `test_msi_mairui_daily_t_midnight_format`：Given t 为 `2025-04-21 00:00:00` 与 `2025-04-21` / Then 同一 trade_date；`2025-04-21 10:00:00` / Then 记录拒绝。
- `test_msi_no_network`：Given 打桩 `egress.mairui_get` / Then 离线导入全程调用 0 次。

## 8. 未验证

BJ 小样本单位证据与批次写库确认的边界、逐入口未验证状态见 [daily-bars-source.md](daily-bars-source.md) §10（T-A172）。

- BJ 路由两只 920 样本小窗口已验证（T-B146b），834682 旧码返回 503；920682 挂接改码前历史、成交量单位为手已验证（`reports/T-B146c.md`，小样本；单位核对仅 1 只 1 日）。全体 BJ 覆盖、920 完整上市以来区间、字段同构仍未验证；第 3 项仅为本批至少到 6116 行未见截断，单次上限与分页机制仍未验证。判据见 [daily-bars-source.md](daily-bars-source.md) §10.7–§10.8（T-A157b）。
- §3.3 目录表列名与主键、§3.4 数值列精度（本契约约定）。
- 麦蕊 1 分钟 v 的单位、t 是开始还是结束、有无 09:30 根（分契 §1.1，单 D 分钟线首次实调核对）。
- 麦蕊 `/hsstock/history` 对 `.BJ` 能否返回历史；官方另有 `/bj/...` 接口族（https://www.mairuiapi.com/bjdata）。
- 北交所新旧代码对照表内容（北交所官网有，库里没有）。
- .lc5 是否也有 13:00 类异常；北交所 .lc5 质量。
- HF 上游数据权利（仓库声明 Apache-2.0，上游不明，T-DATA-SRC）。
- `retest_plan.md` §2.7 的 98% 重叠一致率。
