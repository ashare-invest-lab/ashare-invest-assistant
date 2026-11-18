import { describe, expect, it } from 'vitest';
import type { TodayFocusRow, TodayResponse } from '../api/types';
import { requiresTodayAccount } from '../../../../tests/e2e/mainline-real.helpers';

const held: TodayFocusRow = {
  security_code: '000001.SZ', name: '示例甲', in_watchlist: false, focus: true,
  quote: null, suggestion: null, active_reason_count: 0, max_risk_level: null,
  data_status: 'unavailable', data_as_of: null,
  holding: {
    qty: '100', sellable_qty: '100', cost_price: '10', weight_pct: '100',
    pnl: null, pnl_pct: null, security_type: 'stock', estimated: true,
  },
};
const empty = { items: [], more: false };

function today(overrides: Partial<TodayResponse> = {}): TodayResponse {
  return {
    account_id: '00000000-0000-4000-8000-000000000001',
    server_time: '2026-11-13T10:40:00Z', trade_date: '2026-11-13', session: 'closed',
    market: { regime: null, regime_position_range: null, data_status: 'unavailable' },
    focus: { items: [held], more: false },
    daily_report: { date: '2026-11-13', status: 'ready' },
    reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 },
    pending_plan_drafts: empty, released_reasons: empty, risk_flags: empty,
    invalidations_today: empty, alerts: empty, plan_triggers: empty, data_gaps: empty,
    unread_notifications: 0, evidence: [],
    ...overrides,
  };
}

describe('真环境 E2E 的 today-account 要求（合成 /api/v1/today 响应）', () => {
  it('S3：non_trading_day + ready → 不要求账户卡', () => {
    expect(requiresTodayAccount(today({ session: 'non_trading_day' }))).toBe(false);
  });

  it('S1：无持仓、not_imported + ready → 不要求账户卡', () => {
    expect(requiresTodayAccount(today({
      focus: empty,
      reconciliation: { status: 'not_imported', as_of: null, diff_count: 0, important_count: 0 },
    }))).toBe(false);
  });

  it('交易日、有持仓、ready → 要求账户卡', () => {
    expect(requiresTodayAccount(today())).toBe(true);
  });

  it('S2：已导入但无持仓、ready → 仍要求账户卡', () => {
    expect(requiresTodayAccount(today({ focus: empty }))).toBe(true);
  });

  it('日报未 ready → 不要求账户卡', () => {
    expect(requiresTodayAccount(today({
      daily_report: { date: '2026-11-13', status: 'generating' },
    }))).toBe(false);
  });
});
