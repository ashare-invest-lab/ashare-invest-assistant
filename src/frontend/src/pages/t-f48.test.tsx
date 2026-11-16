import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import type { BrokerAccount } from '../api/accountTypes';
import type { AdminIngestStatus } from '../api/adminTypes';
import type { CandidateVersion } from '../api/candidateTypes';
import type { PlanDraft } from '../api/planTypes';
import type { TerminalQuote, TerminalResponse, TodayResponse } from '../api/types';
import { WatchTable } from '../features/terminal/WatchTable';
import { ChartPanel } from '../features/terminal/ChartPanel';
import { VersionView } from '../features/research/VersionView';
import { TERMINAL_NULL_QUOTE_EXAMPLE, uid } from '../mocks/fixtures';
import { draftsNow } from '../mocks/planHandlers';
import { candidatesNow } from '../mocks/candidateHandlers';
import { mockLoginAs, state } from '../mocks/session';
import { server } from '../mocks/server';
import { patchSignal } from '../mocks/signalHandlers';
import { apiFetch } from '../test/apiFetch';
import { PlanDraftDetailPage } from './plans/PlanDraftDetailPage';
import { PlanDraftsPage } from './plans/PlanDraftsPage';
import { PortfolioPage } from './portfolio/PortfolioPage';
import { ImportWizardPage } from './portfolio/ImportWizardPage';
import { TodayPage } from './today/TodayPage';
import { AdminIngestPage } from './admin/AdminIngestPage';

// 仅替换 canvas，保留 WatchTable、AG Grid、查询和格式化的真实消费路径。
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));

beforeEach(() => mockLoginAs('demo_user'));

function renderPage(element: React.ReactNode, path = '/', route = path) {
  const client = makeQueryClient(true);
  const router = createMemoryRouter([{ path: route, element }], { initialEntries: [path] });
  const view = render(<AppProviders client={client}><RouterProvider router={router} /></AppProviders>);
  return () => { view.unmount(); client.clear(); };
}

it('TerminalQuote 可空字段仍为必填键，价格与时点保持非空', () => {
  const terminal: Pick<TerminalResponse, 'account_id'> = { account_id: null };
  const today: Pick<TodayResponse, 'account_id'> = { account_id: null };
  // @ts-expect-error T-A12 要求回显账户键，无账户时值为 null。
  const missingAccount: Pick<TerminalResponse, 'account_id'> = {};
  const quote: TerminalQuote = { price: '10.240', change_pct: null, amount: null, t: '2026-11-02T15:00:00+08:00' };
  // @ts-expect-error null 与 optional 不同，不能缺 amount。
  const missing: TerminalQuote = { price: quote.price, change_pct: null, t: quote.t };
  // @ts-expect-error 聚合器只在价格存在时返回 quote。
  const noPrice: TerminalQuote = { ...quote, price: null };
  // @ts-expect-error quote 的时点仍非空。
  const noTime: TerminalQuote = { ...quote, t: null };
  expect([quote.amount, noPrice.price, noTime.t]).toEqual([null, null, null]);
  expect(missing).not.toHaveProperty('amount');
  expect([terminal.account_id, today.account_id]).toEqual([null, null]);
  expect(missingAccount).not.toHaveProperty('account_id');
});

it.each([null, '0', '24000'])('WatchTable 成交额 %s：空值显示 —，零和元单位正常显示', async (amount) => {
  const row = { ...TERMINAL_NULL_QUOTE_EXAMPLE, quote: { ...TERMINAL_NULL_QUOTE_EXAMPLE.quote!, amount } };
  const dispose = renderPage(<WatchTable rows={[row]} loading={false} scope="all" onScope={vi.fn()} selected={null} onSelect={vi.fn()} onOpen={vi.fn()} />);
  try {
    const table = screen.getByTestId('watch-table');
    await waitFor(() => expect(table.querySelector('.ag-row [col-id="amount"]')).toHaveTextContent(amount == null ? '—' : amount === '0' ? '0' : '2.4万'));
    expect(table.querySelector('.ag-row [col-id="chg"]')).toHaveTextContent(/^—$/);
    expect(table.querySelector('.ag-row [col-id="price"]')).toHaveTextContent(row.quote.price);
    expect(table.textContent).not.toMatch(/—%|NaN|null|undefined/);
  } finally { dispose(); }
});

it('ChartPanel：amount=null 显示成交额 —，保留价格，涨跌幅不拼接百分号', () => {
  const dispose = renderPage(<ChartPanel row={TERMINAL_NULL_QUOTE_EXAMPLE} suggestion={undefined} tradeDate="2026-11-02" />);
  try {
    const head = screen.getByTestId('quote-head');
    expect(within(head).getByText('成交额 —')).toBeInTheDocument();
    expect(head).toHaveTextContent(TERMINAL_NULL_QUOTE_EXAMPLE.quote!.price);
    expect(head.textContent).not.toMatch(/—%|NaN|null|undefined/);
  } finally { dispose(); }
});

it('WatchTable 排序时区分缺失成交额和真实零值', async () => {
  const rows = ['0', null, '24000'].map((amount, i) => ({
    ...TERMINAL_NULL_QUOTE_EXAMPLE, security_code: `00000${i}.SZ`,
    quote: { ...TERMINAL_NULL_QUOTE_EXAMPLE.quote!, amount },
  }));
  const dispose = renderPage(<WatchTable rows={rows} loading={false} scope="all" onScope={vi.fn()} selected={null} onSelect={vi.fn()} onOpen={vi.fn()} />);
  try {
    const table = screen.getByTestId('watch-table');
    await waitFor(() => expect(table.querySelector('.ag-row[row-index="0"] [col-id="amount"]')).toHaveTextContent(/^0$/));
    fireEvent.click(table.querySelector('.ag-header-cell[col-id="amount"] .ag-header-cell-label')!);
    await waitFor(() => expect(table.querySelector('.ag-row[row-index="0"] [col-id="amount"]')).toHaveTextContent(/^—$/));
    expect(table.querySelector('.ag-row[row-index="1"] [col-id="amount"]')).toHaveTextContent(/^0$/);
  } finally { dispose(); }
});

it('TodayPage：空涨跌幅显示 —，不出现 —% 或 NaN', async () => {
  const etf = { ...TERMINAL_NULL_QUOTE_EXAMPLE, security_code: '510300.SH', name: '合成 ETF',
    quote: { ...TERMINAL_NULL_QUOTE_EXAMPLE.quote!, price: '4.123' } };
  server.use(http.get('/api/v1/today', () => HttpResponse.json({
    account_id: null, server_time: '2026-11-02T15:00:00+08:00', trade_date: '2026-11-02', session: 'closed',
    market: { regime: null, regime_position_range: null, data_status: 'unavailable' },
    focus: { items: [etf], more: false },
    ...Object.fromEntries(['pending_plan_drafts', 'released_reasons', 'risk_flags', 'invalidations_today', 'alerts', 'plan_triggers', 'data_gaps'].map((key) => [key, { items: [], more: false }])),
    daily_report: { date: '2026-11-02', status: 'not_yet' },
    reconciliation: { status: 'not_imported', as_of: null, diff_count: 0, important_count: 0 }, unread_notifications: 0, evidence: [],
  })));
  const dispose = renderPage(<TodayPage />);
  try {
    const name = await screen.findByText(etf.name);
    const row = name.closest('tr')!;
    expect(row).toHaveTextContent('—');
    expect(row.textContent).not.toMatch(/—%|NaN|null|undefined/);
  } finally { dispose(); }
});

it('草案 null 金额、比例、行业占比显示 —，并保留后端缺口原因', async () => {
  const draft: PlanDraft = {
    ...draftsNow()[0], max_loss_amount: null, max_loss_pct: null,
    stops: { stop_loss: null, take_profit: null, time_stop_days: null },
    user_context_snapshot: { holding_qty: '0', sellable_qty: '0', cash: '100', sector_pct: null,
      gaps: [{ key: 'max_loss_amount', reason: 'rc1_disabled' }, { key: 'max_loss_pct', reason: 'no_source' }] },
  };
  server.use(http.get('/api/v1/plan-drafts/:id', () => HttpResponse.json(draft)));
  const dispose = renderPage(<PlanDraftDetailPage />, `/plan-drafts/${draft.id}`, '/plan-drafts/:id');
  try {
    const figures = await screen.findByTestId('draft-figures');
    expect(figures).toHaveTextContent('占总资产 —');
    expect(figures).toHaveTextContent('所属行业占比—');
    expect(figures).toHaveTextContent('未提供止损价');
    expect(figures).toHaveTextContent('止损风控已关闭');
    expect(figures).toHaveTextContent('总资产未知');
    expect(figures.textContent).not.toMatch(/—%|\(%\)|NaN|null|undefined/);
  } finally { dispose(); }
  server.use(http.get('/api/v1/plan-drafts', () => HttpResponse.json({ items: [draft], next_cursor: null })));
  const disposeList = renderPage(<PlanDraftsPage />);
  try {
    const security = await screen.findByText(draft.name);
    expect(security.closest('tr')).toHaveTextContent('— (—)');
  } finally { disposeList(); }
});

it('候选版本 snapshot_id=null 显示快照 —', () => {
  const version: CandidateVersion = { ...candidatesNow()[0].versions[0], snapshot_id: null };
  const dispose = renderPage(<VersionView v={version} />);
  try { expect(screen.getByTestId('cand-version')).toHaveTextContent('快照 —'); }
  finally { dispose(); }
});

it('草案 mock：无止损时不以默认 8% 补造最大亏损', async () => {
  const signal = uid(1011);
  patchSignal(signal, { stops: { stop_loss: null, take_profit: null, time_stop_days: null } });
  const response = await apiFetch('/api/v1/plan-drafts', {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ signal_ids: [signal] }),
  });
  expect(response.status).toBe(201);
  const draft: PlanDraft = await response.json();
  expect([draft.max_loss_amount, draft.max_loss_pct]).toEqual([null, null]);
});

it.each([PortfolioPage, ImportWizardPage])('账户选择：broker_name=null 显示 —', async (Page) => {
  const account: BrokerAccount = { ...state.accounts[0], id: uid(1), alias: '空券商合成账户', broker_name: null };
  server.use(http.get('/api/v1/accounts', () => HttpResponse.json({ items: [account], next_cursor: null })));
  const dispose = renderPage(<Page />);
  try {
    expect(await screen.findByText(/^空券商合成账户 · —/)).toBeInTheDocument();
  } finally { dispose(); }
});

it('采集状态：兼容后端无租约时 leader 的空字段', async () => {
  const status: AdminIngestStatus = {
    heartbeat: 'unknown', leader: { instance_id: null, egress_ip_masked: null, lease_expires_at: null },
    budget: { per_minute_limit: 0, used_last_minute: 0 }, queues: [], errors_24h: [], ip_limit_alerts_24h: 0,
    freshness: [], licences: [], licences_truncated: false, alerts: [],
  };
  server.use(http.get('/api/v1/admin/ingest/status', () => HttpResponse.json(status)));
  const dispose = renderPage(<AdminIngestPage />);
  try {
    expect(await screen.findByText('—（出口 —，租约到 —）')).toBeInTheDocument();
    expect(screen.getByTestId('admin-ingest').textContent).not.toMatch(/null|undefined|Invalid Date/);
  } finally { dispose(); }
});
