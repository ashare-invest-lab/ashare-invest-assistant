import { fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import type { BrokerAccount, BrokerAccountCreate } from '../api/accountTypes';
import type { SecurityReconciliationDiff } from '../api/adminTypes';
import { usePlanDrafts } from '../api/planQueries';
import { useAdminSecurityReconciliation } from '../api/adminQueries';
import type { CandidateVersion } from '../api/candidateTypes';
import type { PlanDraft } from '../api/planTypes';
import type { TerminalQuote, TerminalResponse, TodayResponse } from '../api/types';
import { TerminalPage } from '../features/terminal/TerminalPage';
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
import { AdminSecurityReconciliationPage } from './admin/AdminSecurityReconciliationPage';

// 仅替换 canvas，保留真实页面、AG Grid、查询和格式化的消费路径。
vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));

beforeEach(() => mockLoginAs('demo_user'));

function renderPage(element: React.ReactNode, path = '/', route = path) {
  const client = makeQueryClient(true);
  const router = createMemoryRouter([{ path: route, element }, { path: '/plans/:id', element: <div data-testid="confirmed-plan" /> }], { initialEntries: [path] });
  const view = render(<AppProviders client={client}><RouterProvider router={router} /></AppProviders>);
  return Object.assign(() => { view.unmount(); client.clear(); }, { client, router });
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

it.each([null, '0', '24000'])('GET /terminal：成交额 %s 与空涨跌幅经真实页面显示', async (amount) => {
  const row = { ...TERMINAL_NULL_QUOTE_EXAMPLE, suggestion: null, quote: { ...TERMINAL_NULL_QUOTE_EXAMPLE.quote!, amount } };
  const response: TerminalResponse = {
    account_id: null, account: null, rows: [row], truncated: false, unread_notifications: 0,
    server_time: '2026-11-02T15:00:00+08:00', trade_date: '2026-11-02', session: 'closed',
  };
  server.use(http.get('/api/v1/terminal', () => HttpResponse.json(response)));
  const dispose = renderPage(<TerminalPage />);
  try {
    const table = screen.getByTestId('watch-table');
    await waitFor(() => expect(table.querySelector('.ag-row [col-id="amount"]')).toHaveTextContent(amount == null ? '—' : amount === '0' ? '0' : '2.4万'));
    expect(table.querySelector('.ag-row [col-id="chg"]')).toHaveTextContent(/^—$/);
    expect(table.querySelector('.ag-row [col-id="price"]')).toHaveTextContent(row.quote.price);
    const head = screen.getByTestId('quote-head');
    expect(head).toHaveTextContent(`成交额 ${amount == null ? '—' : amount === '0' ? '0' : '2.4万'}`);
    expect(head).toHaveTextContent(row.quote.price);
    expect(table.textContent + head.textContent).not.toMatch(/—%|NaN|null|undefined/);
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

it.each(['amount', 'chg'])('GET /terminal：%s 排序时 null 与零值不同，升降序均正确', async (column) => {
  // 零值放在 null 前；若把 null 转成 0，稳定排序会保留错误顺序。
  const rows = ['0', null, '24000', '-1'].map((value, i) => ({
    ...TERMINAL_NULL_QUOTE_EXAMPLE, security_code: `00000${i}.SZ`, suggestion: null,
    quote: { ...TERMINAL_NULL_QUOTE_EXAMPLE.quote!, amount: value, change_pct: value },
  }));
  const response: TerminalResponse = {
    account_id: null, account: null, rows, truncated: false, unread_notifications: 0,
    server_time: '2026-11-02T15:00:00+08:00', trade_date: '2026-11-02', session: 'closed',
  };
  server.use(http.get('/api/v1/terminal', () => HttpResponse.json(response)));
  const dispose = renderPage(<TerminalPage />);
  try {
    const table = screen.getByTestId('watch-table');
    const order = () => [0, 1, 2, 3].map((i) => table.querySelector(`.ag-row[row-index="${i}"]`)?.getAttribute('row-id'));
    await waitFor(() => expect(order()).toEqual(rows.map((r) => r.security_code)));
    const header = table.querySelector(`.ag-header-cell[col-id="${column}"] .ag-header-cell-label`)!;
    fireEvent.click(header);
    await waitFor(() => expect(order()).toEqual([rows[1], rows[3], rows[0], rows[2]].map((r) => r.security_code)));
    fireEvent.click(header);
    await waitFor(() => expect(order()).toEqual([rows[2], rows[0], rows[3], rows[1]].map((r) => r.security_code)));
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

function nullDraft(overrides: Partial<PlanDraft> = {}): PlanDraft {
  return {
    ...draftsNow()[0], status: 'pending', max_loss_amount: null, max_loss_pct: null,
    stops: { stop_loss: null, take_profit: null, time_stop_days: null },
    user_context_snapshot: { holding_qty: '0', sellable_qty: '0', cash: '100', sector_pct: null,
      gaps: [{ key: 'max_loss_amount', reason: 'rc1_disabled' }, { key: 'max_loss_pct', reason: 'no_source' }] },
    ...overrides,
  };
}

function expectNullFigures() {
  const figures = screen.getByTestId('draft-figures');
  const loss = within(figures).getByText('最大亏损').closest('div')!;
  expect(loss.querySelector('b')).toHaveTextContent(/^—$/);
  expect(loss).toHaveTextContent('占总资产 —');
  expect(within(figures).getByText('所属行业占比').closest('div')!.querySelector('b')).toHaveTextContent(/^—$/);
  expect(figures).toHaveTextContent('未提供止损价');
  expect(figures).toHaveTextContent('止损风控已关闭');
  expect(figures).toHaveTextContent('总资产未知');
  expect(figures.textContent).not.toMatch(/—%|\(%\)|NaN|null|undefined/);
}

it('GET /plan-drafts/{id}：三个 null 字段显示 —，保留后端缺口原因', async () => {
  const draft = nullDraft();
  server.use(http.get('/api/v1/plan-drafts/:id', () => HttpResponse.json(draft)));
  const dispose = renderPage(<PlanDraftDetailPage />, `/plan-drafts/${draft.id}`, '/plan-drafts/:id');
  try {
    await screen.findByTestId('draft-figures');
    expectNullFigures();
  } finally { dispose(); }
});

it('GET /plan-drafts：亏损金额与比例显示 —，未展示的 sector_pct 经真实 query 保留 null', async () => {
  const draft = nullDraft();
  server.use(http.get('/api/v1/plan-drafts', () => HttpResponse.json({ items: [draft], next_cursor: null })));
  const dispose = renderPage(<PlanDraftsPage />);
  const hook = renderHook(() => usePlanDrafts({ status: [], security_code: '', signal_id: '' }), {
    wrapper: ({ children }) => <AppProviders client={dispose.client}>{children}</AppProviders>,
  });
  try {
    const security = await screen.findByTestId(`draft-link-${draft.id}`);
    expect(security.closest('tr')).toHaveTextContent('— (—)');
    await waitFor(() => expect(hook.result.current.items).toEqual([draft]));
    expect(hook.result.current.items[0].user_context_snapshot.sector_pct).toBeNull();
  } finally { hook.unmount(); dispose(); }
});

it('POST /plan-drafts：真实重新生成入口解析 null 草案，详情页显示 —', async () => {
  const stale = nullDraft({ status: 'stale' });
  const created = nullDraft({ id: uid(4891) });
  const posted = vi.fn();
  server.use(
    http.get('/api/v1/plan-drafts/:id', ({ params }) => HttpResponse.json(params.id === stale.id ? stale : created)),
    http.post('/api/v1/plan-drafts', async ({ request }) => {
      posted(await request.json());
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  const dispose = renderPage(<PlanDraftDetailPage />, `/plan-drafts/${stale.id}`, '/plan-drafts/:id');
  try {
    fireEvent.click(await screen.findByTestId('regen-btn'));
    await waitFor(() => expect(dispose.router.state.location.pathname).toBe(`/plan-drafts/${created.id}`));
    await screen.findByTestId('confirm-form');
    expect(posted).toHaveBeenCalledExactlyOnceWith({ signal_ids: stale.signal_ids });
    // 页面只消费 POST 返回的 id；同时核对真实 mutation 的完整解析结果。
    await waitFor(() => expect(dispose.client.getMutationCache().getAll().map((m) => m.state.data)).toContainEqual(created));
    expectNullFigures();
  } finally { dispose(); }
});

it('POST /plan-drafts/{id}/discard：解析返回的 null 字段，放弃后的详情仍显示 —', async () => {
  let draft = nullDraft();
  const posted = vi.fn();
  server.use(
    http.get('/api/v1/plan-drafts/:id', () => HttpResponse.json(draft)),
    http.post('/api/v1/plan-drafts/:id/discard', async ({ request, params }) => {
      posted(params.id, await request.json());
      draft = { ...draft, status: 'discarded' };
      return HttpResponse.json(draft);
    }),
  );
  const dispose = renderPage(<PlanDraftDetailPage />, `/plan-drafts/${draft.id}`, '/plan-drafts/:id');
  try {
    fireEvent.click(await screen.findByTestId('discard-btn'));
    fireEvent.click(await screen.findByTestId('discard-ok'));
    await screen.findByTestId('draft-discarded');
    expect(posted).toHaveBeenCalledExactlyOnceWith(draft.id, {});
    await waitFor(() => expect(dispose.client.getMutationCache().getAll().map((m) => m.state.data)).toContainEqual(draft));
    expectNullFigures();
  } finally { dispose(); }
});

it('POST /plan-drafts/{id}/confirm：字符串 lot 驱动整手提示，数量和价格以字符串提交', async () => {
  const draft = nullDraft({ action: 'buy', qty_range: { min: '100', max: '1000', lot: '100' } });
  const posted = vi.fn();
  server.use(
    http.get('/api/v1/plan-drafts/:id', () => HttpResponse.json(draft)),
    http.post('/api/v1/plan-drafts/:id/confirm', async ({ request, params }) => {
      posted(params.id, await request.json());
      return HttpResponse.json({ plan_id: uid(4892), plan_version_no: 1 });
    }),
  );
  const dispose = renderPage(<PlanDraftDetailPage />, `/plan-drafts/${draft.id}`, '/plan-drafts/:id');
  try {
    const qty = await screen.findByTestId('chosen-qty');
    expect(screen.getByTestId('draft-figures')).toHaveTextContent('每手 100');
    fireEvent.change(qty, { target: { value: '150' } });
    expect(screen.getByTestId('lot-warning')).toHaveTextContent('按 100 股递增');
    fireEvent.change(qty, { target: { value: '200' } });
    expect(screen.queryByTestId('lot-warning')).not.toBeInTheDocument();
    for (const c of draft.judgment_checklist.filter((c) => c.required)) {
      fireEvent.click(within(screen.getByTestId(`answer-${c.id}`)).getByText('是'));
    }
    fireEvent.click(screen.getByTestId('risk-ack'));
    fireEvent.click(screen.getByTestId('confirm-btn'));
    fireEvent.click(await screen.findByTestId('review-ok'));
    await screen.findByTestId('confirmed-plan');
    expect(posted).toHaveBeenCalledExactlyOnceWith(draft.id, {
      checklist_answers: draft.judgment_checklist.filter((c) => c.required).map((c) => ({ id: c.id, answer: 'yes' })),
      risk_ack: true, chosen_qty: '200', chosen_price: draft.price_range.low, deviation_ack: false,
    });
  } finally { dispose(); }
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

it('POST /accounts：请求类型拒绝 null/缺键；表单拒绝空值与纯空格，填写后才提交', async () => {
  // @ts-expect-error GET 可空不代表 POST 允许 null。
  const nullBroker: BrokerAccountCreate = { alias: '合成账户', broker_name: null };
  // @ts-expect-error POST 的 broker_name 仍为必填键。
  const missingBroker: BrokerAccountCreate = { alias: '合成账户' };
  expect(nullBroker.broker_name).toBeNull();
  expect(missingBroker).not.toHaveProperty('broker_name');
  const posted = vi.fn();
  server.use(
    http.get('/api/v1/accounts', () => HttpResponse.json({ items: [], next_cursor: null })),
    http.post('/api/v1/accounts', async ({ request }) => {
      const body = await request.json();
      posted(body);
      return HttpResponse.json({ ...state.accounts[0], id: uid(4893), ...body as BrokerAccountCreate }, { status: 201 });
    }),
  );
  const dispose = renderPage(<PortfolioPage />);
  try {
    fireEvent.click(await screen.findByRole('button', { name: '新建账户' }));
    const dialog = within(await screen.findByRole('dialog'));
    fireEvent.change(dialog.getByLabelText('账户别名'), { target: { value: '合成账户' } });
    for (const value of ['', '   ']) {
      fireEvent.change(dialog.getByLabelText('券商'), { target: { value } });
      fireEvent.click(dialog.getByRole('button', { name: /创\s*建/ }));
      await waitFor(() => expect(dialog.getByLabelText('券商')).toHaveAttribute('aria-invalid', 'true'));
      expect(await dialog.findByText('请输入券商名称')).toBeInTheDocument();
      expect(posted).not.toHaveBeenCalled();
    }
    fireEvent.change(dialog.getByLabelText('券商'), { target: { value: '合成券商' } });
    fireEvent.click(dialog.getByRole('button', { name: /创\s*建/ }));
    await waitFor(() => expect(posted).toHaveBeenCalledExactlyOnceWith({ alias: '合成账户', broker_name: '合成券商' }));
  } finally { dispose(); }
});

it('GET /admin/securities/reconciliation：大整数 diff.id 在 query 和页面行标识中保持字符串精度', async () => {
  mockLoginAs('admin');
  const id = '9223372036854775807';
  const diff: SecurityReconciliationDiff = {
    id, kind: 'field_mismatch', source: 'cninfo', security_code: '609999.SH', name: '合成证券', source_name: '合成简称',
    field: 'name', master_value: '合成证券', source_value: '合成简称', licence_owner: null,
    first_seen_on: '2026-11-01', last_seen_on: '2026-11-02', seen_days: 2, status: 'open', resolved_on: null,
  };
  // @ts-expect-error diff.id 使用十进制字符串，不得恢复为 number。
  const numericId: SecurityReconciliationDiff['id'] = 1;
  expect(numericId).toBe(1);
  server.use(http.get('/api/v1/admin/securities/reconciliation', () => HttpResponse.json({ items: [diff], next_cursor: null })));
  const dispose = renderPage(<AdminSecurityReconciliationPage />);
  const hook = renderHook(() => useAdminSecurityReconciliation({ status: 'open', kinds: [], source: null }), {
    wrapper: ({ children }) => <AppProviders client={dispose.client}>{children}</AppProviders>,
  });
  try {
    await waitFor(() => expect(hook.result.current.items[0]?.id).toBe(id));
    expect(typeof hook.result.current.items[0].id).toBe('string');
    // 页面没有 id 文本列；实际 rowKey 和差异单元格标识必须逐字保留该 id。
    const cell = await screen.findByTestId(`recon-diff-${id}`);
    expect(cell.closest('tr')).toHaveAttribute('data-row-key', id);
    expect(cell).toHaveTextContent('主数据 合成证券 ／ 对方 合成简称');
  } finally { hook.unmount(); dispose(); }
});
