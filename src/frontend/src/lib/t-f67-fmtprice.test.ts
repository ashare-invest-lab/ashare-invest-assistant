import { describe, expect, it } from 'vitest';
import { fmtPrice } from './format';

const price = fmtPrice as unknown as (value: string | number | null | undefined, securityType?: string) => string;

describe('T-F67 fmtPrice', () => {
  it('保留股票既有两位规则', () => {
    expect(price('187.5800', 'stock')).toBe('187.58');
  });

  const etfCases = [price('3.12', 'etf'), price('3.120', 'etf')];
  (etfCases.every((value) => value === '3.120') ? it : it.fails)('ETF 显示三位并补尾零（T-F67）', () => {
    expect(price('3.12', 'etf')).toBe('3.120');
    expect(price('3.120', 'etf')).toBe('3.120');
  });

  it('ETF 空值仍显示缺失标记', () => {
    expect(price(null, 'etf')).toBe('—');
  });
});
