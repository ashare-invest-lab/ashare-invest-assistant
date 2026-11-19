import { labelOf, tagOf } from './explanations';
import { reconKindText, reconSourceText } from '../i18n/reconLabels';
import { causeText } from '../i18n/signalLabels';
import { capExplanation } from '../i18n/horizonCaps';

it.each(['future_value', '__proto__', 'constructor'])('运行时查表拒绝非自有键 %s', (key) => {
  const labels = { known: '已知' };
  const tags = { known: { text: '已知', color: 'blue' } };
  expect(labelOf(labels, key)).toBeUndefined();
  expect(tagOf(tags, key)).toEqual({ text: '未知', color: undefined });
  expect(labelOf(labels, key) ?? key).toBe(key);
  expect(reconKindText(key)).toBe(key);
  expect(reconSourceText(key)).toBe(key);
  expect(causeText(key)).toBe(key);
  expect(capExplanation({ kind: 'gate', rule_id: key, horizon: 'short', cap: 0, inputs_missing: [] })).toBe(`闸门 ${key} 命中`);
});

it('自有键正常映射，保留假值；null 与 undefined 走兜底', () => {
  const labels = { known: '已知', empty: '', zero: 0, disabled: false };
  expect(labelOf(labels, 'known')).toBe('已知');
  expect(labelOf(labels, 'empty')).toBe('');
  expect(labelOf(labels, 'zero')).toBe(0);
  expect(labelOf(labels, 'disabled')).toBe(false);
  expect(labelOf(labels, null)).toBeUndefined();
  expect(labelOf(labels, undefined)).toBeUndefined();
  const tag = { text: '已知', color: 'blue' };
  expect(tagOf({ known: tag }, 'known')).toBe(tag);
});

it('仅信任自有白名单：自定义原型属性不可映射，无原型对象可映射', () => {
  const inherited = Object.create({ inherited: '原型标签' }) as Record<string, string>;
  inherited.known = '自有标签';
  expect(labelOf(inherited, 'inherited')).toBeUndefined();
  expect(labelOf(inherited, 'known')).toBe('自有标签');
  const bare = Object.create(null) as Record<string, string>;
  bare.known = '已知';
  expect(labelOf(bare, 'known')).toBe('已知');
  expect(labelOf(bare, '__proto__')).toBeUndefined();
});
