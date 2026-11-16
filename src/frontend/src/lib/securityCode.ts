/** 证券完整代码格式；显式后缀也支持 ETF、指数等证券。 */
export const CODE_RE = /^\d{6}\.(SH|SZ|BJ)$/;

/** 裸股票代码按代码段补全；不为未知代码段猜测交易所，是否存在仍由主数据确认。 */
export function completeSecurityCode(raw: string): string | null {
  const code = raw.normalize('NFKC').trim().toUpperCase();
  if (CODE_RE.test(code)) return code;
  if (!/^\d{6}$/.test(code)) return null;
  if (/^(300|301|000|001|002|003)/.test(code)) return `${code}.SZ`;
  if (/^(600|601|603|605|688|689)/.test(code)) return `${code}.SH`;
  if (/^(92|8|4)/.test(code)) return `${code}.BJ`;
  return null;
}
