import { REASON_CODES } from './enums';
import { REASON_CODE } from '../i18n/labels';
import { REASONS } from '../mocks/fixtures';

describe('T-F81 SAME_TEMPLATE_COOLDOWN', () => {
  it('原因码表有 23 个值并提供中文名称', () => {
    expect(REASON_CODES).toHaveLength(23);
    expect(REASON_CODES).toContain('SAME_TEMPLATE_COOLDOWN');
    expect(Object.hasOwn(REASON_CODE, 'SAME_TEMPLATE_COOLDOWN')).toBe(true);
    expect(REASON_CODE.SAME_TEMPLATE_COOLDOWN).toBe('同模板同证券冷却');
  });

  it('夹具包含自动到期的时间解除条件', () => {
    const reasons = REASONS.filter((r) => r.code === 'SAME_TEMPLATE_COOLDOWN');
    expect(reasons).toHaveLength(1);
    expect(reasons[0].release_condition).toEqual({
      kind: 'time',
      expr: null,
      at: '2026-11-05T15:00:00+08:00',
      event: null,
      action: null,
      check_on: ['schedule'],
      human_text: '同模板同证券冷却至到期交易日15:00（北京时间）',
      machine_checkable: true,
    });
  });
});
