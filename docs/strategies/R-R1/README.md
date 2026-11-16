# R-R1：公开ST与终止上市名单核对报告
2026-11-15 00:58–01:05 MST共12次公开GET；采用6份规范输入（均HTTP 200），另5份空结果及1份被规范参数版本替代的响应只留原证，不作名单。
[来源、URL、时刻与SHA](sources.json)｜[完整核对结果](check_result.json)；原始响应留`F:/workspace/team/reports/R-R1/public-raw-v1/`，旧深市公开XLSX的SHA与T-R65 manifest核等。
[当前ST名单](st_current.csv)共193只：深113（ST 64、*ST 49，截至2026-11-13），沪80（ST 42、*ST 38，2026-11-15实取）；仅认规范化简称前缀，“退”与已终止分列。
[当前终止上市A股名单](termination_current.csv)共338条：深190、沪148；另排除当前列表1只科创板CDR，不混入A股。
[差异清单](differences.csv)共6项：深市新增300901“中胤时尚→中胤科技”、301015“百洋医药→百洋制药”，两条均非ST切换。
深市终止A股189→190：新增002731萃华退，终止上市日2026-11-13；其当前简称状态由“退”转为“已终止”，深市ST总数113不变。
沪市当前ST 80，相对`security_master.md`的2026-11-01汇总数81为-1；没有旧逐代码快照，不能据此指认具体新增或摘帽股票。
600190存在来源冲突：[2025-07-18摘牌公告](https://www.sse.com.cn/disclosure/announcement/listing/stock/c/c_20250718_10785880.shtml)明文2025-07-25，当前上交所`DELIST_DATE`为2025-07-28；双值保留，未改写来源。
90个已登记公开终止记录交叉核89个一致、仅上述1个冲突；T-R65沪市终止总数148一致，600543仍为*ST莫高。
离线9项测试及Ruff通过；复跑：`python -I -B docs/strategies/R-R1/test_audit_public_lists.py`。
归档复算：`python -I -B docs/strategies/R-R1/audit_public_lists.py --raw-dir F:/workspace/team/reports/R-R1/public-raw-v1 --old-szse-name F:/tdata-st-research/szse_name_change_20261110.xlsx --old-szse-termination F:/tdata-st-research/szse_delist.xlsx --write`。
限制：深市为旧新公开表全量差分；沪市旧ST仅汇总对比、旧终止仅核36个公开键，不冒称148项逐项旧新比较。
未读原337行CSV、数据库、私有样本或真实持仓；不做F23准确率、策略规则、r2、麦蕊调用、交易或部署。
