import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { MemoryRouter } from 'react-router';
import { useTerminal } from '../../api/queries';
import type { Restriction, TodayResponse } from '../../api/types';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { errorBody, notFound } from '../../mocks/handlerUtils';
import { server } from '../../mocks/server';
import { RestrictionsPage } from './RestrictionsPage';
import { TodayPage } from '../today/TodayPage';

const API = '/api/v1';
const restriction: Restriction = {
  id: 'restriction-t-f70', kind: 'blocklist', target_type: 'security', target_id: '600000.SH', name: '示例银行',
  until: null, reason: '示例原因', status: 'active', created_at: '2026-11-21T09:00:00+08:00', removed_at: null,
};

function renderPage() {
  render(<AppProviders client={makeQueryClient(true)}><MemoryRouter><RestrictionsPage /></MemoryRouter></AppProviders>);
}

function todayBody(released: TodayResponse['released_reasons']['items']): TodayResponse {
  return {
    account_id: null, server_time: '2026-11-21T10:00:00+08:00', trade_date: '2026-11-21', session: 'morning',
    market: { regime: null, regime_position_range: null, data_status: 'fresh' },
    focus: { items: [], more: false }, pending_plan_drafts: { items: [], more: false },
    released_reasons: { items: released, more: false }, risk_flags: { items: [], more: false },
    invalidations_today: { items: [], more: false }, daily_report: { date: '2026-11-21', status: 'not_yet' },
    reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 }, unread_notifications: 0,
    alerts: { items: [], more: false }, plan_triggers: { items: [], more: false }, data_gaps: { items: [], more: false }, evidence: [],
  };
}

function TerminalCount() {
  const q = useTerminal('all');
  return <span data-testid="terminal-count">{q.data?.rows[0]?.active_reason_count ?? (q.error ? 'error' : 'loading')}</span>;
}

describe('T-F70 /restrictions R6', () => {
  it('GET、POST、DELETE 错误分别显示 ErrorBox', async () => {
    server.use(http.get(`${API}/restrictions`, () => HttpResponse.json(errorBody('INTERNAL_ERROR', '列表失败'), { status: 500 })));
    renderPage();
    expect((await screen.findByRole('alert')).getAttribute('data-code')).toBe('INTERNAL_ERROR');

    cleanup();
    server.resetHandlers();
    server.use(http.post(`${API}/restrictions`, () => HttpResponse.json(errorBody('VALIDATION_ERROR', '目标不可用'), { status: 400 })));
    renderPage();
    await userEvent.setup().type(await screen.findByLabelText('目标 ID'), '600000.SH');
    await userEvent.setup().click(screen.getAllByTestId('restriction-create').at(-1)!);
    expect((await screen.findByRole('alert')).getAttribute('data-code')).toBe('VALIDATION_ERROR');

    cleanup();
    server.resetHandlers();
    server.use(
      http.get(`${API}/restrictions`, () => HttpResponse.json({ items: [restriction], next_cursor: null })),
      http.delete(`${API}/restrictions/:id`, () => notFound('限制项')),
    );
    renderPage();
    await userEvent.setup().click(await screen.findByTestId(`restriction-delete-${restriction.id}`));
    expect((await screen.findByRole('alert')).getAttribute('data-code')).toBe('NOT_FOUND');
  });

  it('空列表是成功空态，可带空 gaps', async () => {
    server.use(http.get(`${API}/restrictions`, () => HttpResponse.json({ items: [], next_cursor: null, gaps: [] })));
    renderPage();
    expect(await screen.findByText('暂无限制项。你可以在上方新增禁投、冷静期或屏蔽。')).toBeInTheDocument();
    expect(screen.queryByTestId('restriction-list-gaps')).not.toBeInTheDocument();
  });

  it('整页重挂载会再次请求列表并展示最新载荷', async () => {
    let calls = 0;
    const refreshed: Restriction = { ...restriction, id: 'restriction-refreshed', target_id: '000001.SZ', name: '刷新后证券' };
    server.use(http.get(`${API}/restrictions`, () => {
      calls += 1;
      return HttpResponse.json({ items: calls === 1 ? [restriction] : [refreshed], next_cursor: null, gaps: [] });
    }));
    const view = render(<AppProviders client={makeQueryClient(true)}><MemoryRouter><RestrictionsPage /></MemoryRouter></AppProviders>);
    expect(await screen.findByText('示例银行')).toBeInTheDocument();
    expect(calls).toBe(1);

    view.unmount();
    render(<AppProviders client={makeQueryClient(true)}><MemoryRouter><RestrictionsPage /></MemoryRouter></AppProviders>);
    expect(await screen.findByText('刷新后证券')).toBeInTheDocument();
    expect(calls).toBe(2);
    expect(screen.queryByText('示例银行')).not.toBeInTheDocument();
  });

  it('限制项和列表/重查缺口的未知枚举一律显示未知', async () => {
    const unknownItems: Restriction[] = [
      { ...restriction, id: 'restriction-unknown-proto', kind: '__proto__' as Restriction['kind'], target_type: 'constructor' as Restriction['target_type'], status: 'unfamiliar-status', target_id: 'example-unknown-proto', name: null },
      { ...restriction, id: 'restriction-unknown-constructor', kind: 'constructor' as Restriction['kind'], target_type: 'unfamiliar-target' as Restriction['target_type'], status: '__proto__', target_id: 'example-unknown-constructor', name: null },
      { ...restriction, id: 'restriction-unknown-unfamiliar', kind: 'unfamiliar-kind' as Restriction['kind'], target_type: '__proto__' as Restriction['target_type'], status: 'constructor', target_id: 'example-unknown-unfamiliar', name: null },
    ];
    const listGaps = [
      { key: 'restriction.list.proto', reason: '__proto__', message: '列表原型键缺口' },
      { key: 'restriction.list.constructor', reason: 'constructor', message: '列表构造键缺口' },
      { key: 'restriction.list.unfamiliar', reason: 'unfamiliar-gap-reason', message: '列表未列缺口' },
    ];
    const recheckGaps = [
      { key: 'restriction.recheck.proto', reason: '__proto__', message: '重查原型键缺口' },
      { key: 'restriction.recheck.constructor', reason: 'constructor', message: '重查构造键缺口' },
      { key: 'restriction.recheck.unfamiliar', reason: 'unfamiliar-gap-reason', message: '重查未列缺口' },
    ];
    server.use(
      http.get(`${API}/restrictions`, () => HttpResponse.json({ items: unknownItems, next_cursor: null, gaps: listGaps })),
      http.delete(`${API}/restrictions/:id`, () => HttpResponse.json({
        id: unknownItems[0].id, removed_at: '2026-11-21T10:03:00+08:00',
        recheck: { released_reason_ids: [], remaining_reason_ids: ['reason-unknown'] }, gaps: recheckGaps,
      })),
    );
    renderPage();
    expect(await screen.findAllByText('未知')).toHaveLength(9);
    expect(screen.getByTestId('restriction-list-gaps')).toHaveTextContent('未知（列表原型键缺口）；未知（列表构造键缺口）；未知（列表未列缺口）');
    await userEvent.setup().click(await screen.findByTestId(`restriction-delete-${unknownItems[0].id}`));
    expect(await screen.findByTestId('restriction-recheck-gaps')).toHaveTextContent('未知（重查原型键缺口）；未知（重查构造键缺口）；未知（重查未列缺口）');
    expect(screen.getByTestId('restriction-recheck')).toHaveTextContent('当前状态不能判定为解除');
  });

  it('展示列表与删除重查 gaps，gap 时不宣称解除或可交易', async () => {
    const gap = { key: 'restriction.recheck', reason: 'no_source', message: '重查来源缺失' } as const;
    server.use(
      http.get(`${API}/restrictions`, () => HttpResponse.json({ items: [restriction], next_cursor: null, gaps: [gap] })),
      http.delete(`${API}/restrictions/:id`, () => HttpResponse.json({ id: restriction.id, removed_at: '2026-11-21T10:01:00+08:00', recheck: { released_reason_ids: [], remaining_reason_ids: ['reason-1'] }, gaps: [gap] })),
    );
    renderPage();
    expect(await screen.findByTestId('restriction-list-gaps')).toHaveTextContent('重查未完成');
    await userEvent.setup().click(await screen.findByTestId(`restriction-delete-${restriction.id}`));
    expect(await screen.findByTestId('restriction-recheck-gaps')).toHaveTextContent('重查未完成');
    expect(screen.getByTestId('restriction-recheck')).toHaveTextContent('剩余原因 1 项');
    expect(screen.queryByText(/已解除|已可交易/)).not.toBeInTheDocument();
  });

  it('删除成功刷新终端计数与今日解除列表，gap 不会伪造解除', async () => {
    let removed = false;
    let terminalCount = 1;
    let todayCalls = 0;
    let released: TodayResponse['released_reasons']['items'] = [];
    const releasedRow = { reason_id: 'reason-1', signal_id: 'signal-1', code: 'BLOCKLISTED' as const, security_code: '600000.SH', name: '示例银行', released_at: '2026-11-21T10:02:00+08:00' };
    server.use(
      http.get(`${API}/restrictions`, () => HttpResponse.json({ items: removed ? [] : [restriction], next_cursor: null })),
      http.delete(`${API}/restrictions/:id`, () => { removed = true; terminalCount = 0; return HttpResponse.json({ id: restriction.id, removed_at: '2026-11-21T10:02:00+08:00', recheck: { released_reason_ids: [], remaining_reason_ids: [] }, gaps: [{ key: 'restriction.recheck', reason: 'no_source', message: '重查来源缺失' }] }); }),
      http.get(`${API}/terminal`, () => HttpResponse.json({ account_id: null, server_time: '2026-11-21T10:00:00+08:00', trade_date: '2026-11-21', session: 'morning', account: null, rows: [{ ...restriction, security_code: '600000.SH', name: '示例银行', in_watchlist: true, focus: true, quote: null, holding: null, suggestion: { id: 'suggestion-1', created_at: '2026-11-21T09:00:00+08:00', status: 'active', consensus: 'single', actions: [], executability_status: 'blocked', divergent_dimensions: [], top_score: null }, active_reason_count: terminalCount, max_risk_level: null, data_status: 'fresh', data_as_of: null }], truncated: false, unread_notifications: 0 })),
      http.get(`${API}/today`, () => { todayCalls += 1; return HttpResponse.json(todayBody(released)); }),
    );
    const client = makeQueryClient(true);
    render(<AppProviders client={client}><MemoryRouter><RestrictionsPage /><TodayPage /><TerminalCount /></MemoryRouter></AppProviders>);
    await waitFor(() => expect(screen.getByTestId('terminal-count')).toHaveTextContent('1'));
    await userEvent.setup().click(await screen.findByTestId(`restriction-delete-${restriction.id}`));
    await waitFor(() => expect(screen.getByTestId('terminal-count')).toHaveTextContent('0'));
    await waitFor(() => expect(todayCalls).toBeGreaterThan(1));
    expect(within(screen.getByTestId('today-released')).queryByText('示例银行')).not.toBeInTheDocument();
    released = [releasedRow];
    await client.invalidateQueries({ queryKey: ['today'] });
    expect(await within(screen.getByTestId('today-released')).findByText('示例银行')).toBeInTheDocument();
  });
});
