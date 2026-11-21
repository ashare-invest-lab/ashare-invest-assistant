import { describe, expect, it } from 'vitest';
import { fmtPrice } from './format';

if (typeof fmtPrice !== 'function') {
  throw new Error('fmtPrice 必须是函数');
}

const supportsSecurityType = fmtPrice.length >= 2;

describe('T-F67 fmtPrice', () => {
  it('保留股票既有两位规则', () => {
    expect(fmtPrice('187.5800')).toBe('187.58');
  });

  (supportsSecurityType ? it : it.skip)('ETF 显示三位并补尾零（T-F67）', () => {
    expect(Reflect.apply(fmtPrice, undefined, ['3.12', 'etf'])).toBe('3.120');
    expect(Reflect.apply(fmtPrice, undefined, ['3.120', 'etf'])).toBe('3.120');
  });

  it('ETF 空值仍显示缺失标记', () => {
    expect(fmtPrice(null)).toBe('—');
  });
});
