# W-01 v2 · 长园集团前三季度归母净利润同比复算

B3／T-R99，核对日 2026-11-20（丹佛）。固定报告期为 2024 年 1–9 月，比较期为 2023 年 1–9 月。长园科技集团股份有限公司（600525）的更正公告同时调整了本期和上年同期。按 [F22](https://github.com/ashare-invest-lab/ashare-invest-assistant/blob/239ea6b73991b302bd06e795fdb14a7abcad9925/docs/strategies/feature_spec.md#L298-L303) 取合并利润表中归属于母公司股东的净利润，按 `(本期 ÷ 上年同期 − 1) × 100` 复算，两期均为累计金额。

| 公告版本（北京时间披露日） | 2024 年 1–9 月（元） | 2023 年 1–9 月（元） | 同比（%） | 巨潮所载公司原件（PDF 页码） |
|---|---:|---:|---:|---|
| 2024-10-29 原三季报 | −59,253,788.60 | 101,424,061.94 | −158.42 | [2024 三季报第 12 页，两期并列](https://static.cninfo.com.cn/finalpage/2024-10-29/1221542079.PDF#page=12)；[2023-10-28 原三季报第 12 页，核基期](https://static.cninfo.com.cn/finalpage/2023-10-28/1218190788.PDF#page=12) |
| 2025-04-29 更正公告，取两期调整后金额 | −49,157,879.76 | 100,482,817.83 | −148.92 | [更正公告第 20 页，本期](https://static.cninfo.com.cn/finalpage/2025-04-29/1223389862.PDF#page=20)；[同一公告第 4 页，基期](https://static.cninfo.com.cn/finalpage/2025-04-29/1223389862.PDF#page=4) |

本期调增 10,095,908.84 元，基期调减 941,244.11 元。两版分别计算、最后保留两位小数，同比相差 **9.50 个百分点**。原版复算与[2024 三季报第 1 页「年初至报告期末」同比](https://static.cninfo.com.cn/finalpage/2024-10-29/1221542079.PDF#page=1)一致。更正后同比是对该历史报告期的复算；更正披露时还应按查询时点选择最新报告期。

公告目录能确认上述披露日。供应商两个版本的首次可见时刻、是否保留旧行及更正行 `plrq` 仍待 V5f 核实。仓内以 `next_trading_day(plrq) 09:30`（北京时间）为规则，并记录首次观测的 `observed_at`，更正另存。复算限于公开报表，F22 维持 `verified_doc`，W-01 的 F21 来源审核及 G6 真实 120 交易日账本仍待验。[仓内版本规则](https://github.com/ashare-invest-lab/ashare-invest-assistant/blob/239ea6b73991b302bd06e795fdb14a7abcad9925/docs/strategies/feature_spec.md#L930-L936)
