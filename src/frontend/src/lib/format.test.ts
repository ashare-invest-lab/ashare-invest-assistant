import { afterAll, describe, expect, it } from 'vitest';
import { fmtPrice, fmtTime } from './format';

const ORIGINAL_TZ = process.env.TZ;
const inputs = [
  '2026-11-10T02:31:00Z',
  '2026-11-10T10:31:00+08:00',
  '2026-11-10T10:31:05+08:00',
  '2026-11-09T19:31:00-07:00',
  '2026-11-10T02:31:00.000Z',
  'not-a-time',
  '2026-11-10',
];
const expected = [
  '2026-11-10 10:31',
  '2026-11-10 10:31',
  '2026-11-10 10:31:05',
  '2026-11-10 10:31',
  '2026-11-10 10:31',
  'not-a-time',
  '2026-11-10',
];

afterAll(() => {
  if (ORIGINAL_TZ === undefined) delete process.env.TZ;
  else process.env.TZ = ORIGINAL_TZ;
});

describe('fmtTime 北京时间显示', () => {
  it('t-f37 fmtTime Z 结尾换算北京时间', () => {
    process.env.TZ = 'America/Denver';
    expect(fmtTime('2026-11-10T02:31:00Z')).toBe('2026-11-10 10:31');
  });

  it('t-f37 fmtTime +08:00 输出不变', () => {
    expect(fmtTime('2026-11-10T10:31:00+08:00')).toBe('2026-11-10 10:31');
    expect(fmtTime('2026-11-10T10:31:05+08:00')).toBe('2026-11-10 10:31:05');
  });

  it('t-f37 fmtTime 其他偏移换算', () => {
    expect(fmtTime('2026-11-09T19:31:00-07:00')).toBe('2026-11-10 10:31');
    expect(fmtTime('2026-11-10T02:31:00.000Z')).toBe('2026-11-10 10:31');
  });

  it('t-f37 fmtTime 非法输入原样返回', () => {
    expect(() => fmtTime('not-a-time')).not.toThrow();
    expect(fmtTime('not-a-time')).toBe('not-a-time');
    expect(fmtTime('2026-11-10')).toBe('2026-11-10');
  });

  it('t-f37 fmtTime 与机器时区无关', () => {
    for (const tz of ['America/Denver', 'UTC', 'Asia/Shanghai']) {
      process.env.TZ = tz;
      expect(inputs.map(fmtTime)).toEqual(expected);
    }
  });
});

describe('T-F47 秒级时间与价格位数', () => {
  it('fmtTime 截去微秒', () => {
    expect(fmtTime('2026-11-13T15:06:59.586199+08:00')).toBe('2026-11-13 15:06:59');
    expect(fmtTime('2026-11-13 15:06:59.586199')).toBe('2026-11-13 15:06:59');
  });
  it('fmtPrice 2 到 3 位小数', () => {
    expect(fmtPrice('187.5800')).toBe('187.58');
    expect(fmtPrice('3.1230')).toBe('3.123');
    expect(fmtPrice(null)).toBe('—');
  });
});
