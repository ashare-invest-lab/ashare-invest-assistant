/** T-F41 回归：以下 MSW 响应均为示例数据，不连接真实行情源。 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { BarsResponse } from '../api/types';
import type { Announcement, AnnouncementsResponse, FactorValue, FactorsResponse, FinancialPeriod, FinancialsResponse, FundFlowDay, FundFlowsResponse, SecurityProfile } from '../api/marketTypes';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { securityProfile } from '../mocks/marketFixtures';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { completeSecurityCode } from '../lib/securityCode';
import { preloadRoutes } from './preloadRoutes';

const fault = vi.hoisted(() => ({ module: '', realCharts: false }));
vi.mock('../components/charts/KlineChart', async (original) => {
  const actual = await original<typeof import('../components/charts/KlineChart')>();
  return { KlineChart: (props: Parameters<typeof actual.KlineChart>[0]) => {
    if (fault.module === 'kline') throw new Error('示例数据：K 线渲染异常');
    return fault.realCharts ? <actual.KlineChart {...props} /> : <div data-testid="kline" />;
  } };
});
vi.mock('../components/charts/IntradayChart', async (original) => {
  const actual = await original<typeof import('../components/charts/IntradayChart')>();
  return { IntradayChart: (props: Parameters<typeof actual.IntradayChart>[0]) => {
    if (fault.module === 'intraday') throw new Error('示例数据：分时渲染异常');
    return fault.realCharts ? <actual.IntradayChart {...props} /> : <div data-testid="intraday" />;
  } };
});
vi.mock('../components/charts/FundFlowChart', async (original) => {
  const actual = await original<typeof import('../components/charts/FundFlowChart')>();
  return { FundFlowChart: (props: Parameters<typeof actual.FundFlowChart>[0]) => fault.realCharts ? <actual.FundFlowChart {...props} /> : <div /> };
});
// 只替换浏览器绘图库，空值回归执行真实 Kline/Intraday/FundFlowChart 的数据转换。
vi.mock('lightweight-charts', async (original) => ({
  ...await original<typeof import('lightweight-charts')>(),
  createSeriesMarkers: vi.fn(),
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn(), createPriceLine: vi.fn(), priceScale: () => ({ applyOptions: vi.fn() }) }),
    priceScale: () => ({ applyOptions: vi.fn() }),
    timeScale: () => ({
      fitContent: vi.fn(), setVisibleLogicalRange: vi.fn(), getVisibleLogicalRange: () => null,
      subscribeVisibleLogicalRangeChange: vi.fn(), unsubscribeVisibleLogicalRangeChange: vi.fn(),
    }),
    remove: vi.fn(),
  }),
}));
vi.mock('../features/research/AddToResearch', async (original) => {
  const actual = await original<typeof import('../features/research/AddToResearch')>();
  return { AddToResearch: (props: Parameters<typeof actual.AddToResearch>[0]) => {
    if (fault.module === 'header') throw new Error('示例数据：行情头渲染异常');
    return <actual.AddToResearch {...props} />;
  } };
});
vi.mock('../pages/stock/StockTabs', async (original) => {
  const actual = await original<typeof import('../pages/stock/StockTabs')>();
  const wrap = (name: string, Tab: typeof actual.FinancialsTab) => (props: { code: string }) => {
    if (fault.module === name) throw new Error(`示例数据：${name} 渲染异常`);
    return <Tab {...props} />;
  };
  return { ...actual,
    FinancialsTab: wrap('financials', actual.FinancialsTab), FundFlowTab: wrap('fund-flow', actual.FundFlowTab),
    FactorsTab: wrap('factors', actual.FactorsTab), AnnouncementsTab: wrap('announcements', actual.AnnouncementsTab),
  };
});

const API = '/api/v1';
const stamp = '2026-11-13T15:00:00+08:00';
const code = '300502.SZ';

function bars(securityCode: string, freq: BarsResponse['freq']): BarsResponse {
  return {
    security_code: securityCode, name: '示例数据证券', freq, adjust: freq === '1m' ? 'none' : 'qfq',
    pre_close: '10.00', adjust_as_of: freq === '1m' ? null : '2026-11-13', next_before: null,
    items: [{ t: stamp, open: '10.00', high: '10.50', low: '9.80', close: '10.20', pre_close: '10.00',
      volume: '10000', amount: '102000', avg_price: null, is_final: true }],
    data_status: 'fresh', data_as_of: stamp, gaps: [],
  };
}

function apiError(status: number) {
  return HttpResponse.json({ error: {
    code: status === 404 ? 'NOT_FOUND' : status === 422 ? 'VALIDATION_ERROR' : 'INTERNAL_ERROR',
    message: '示例数据：接口暂不可用', details: null, request_id: 'example-t-f41',
  } }, { status });
}

beforeAll(() => preloadRoutes(routes), 60_000);
beforeEach(() => {
  fault.module = '';
  fault.realCharts = false;
  mockLoginAs('demo_user');
  server.use(
    http.get(`${API}/securities/search`, () => HttpResponse.json({ items: [], master_as_of: '2026-11-13' })),
    http.get(`${API}/securities/:code`, ({ params }) => HttpResponse.json({
      ...securityProfile('600000.SH')!, security_code: String(params.code), name: '示例数据证券',
      exchange: String(params.code).slice(-2), suspended: false,
    })),
    http.get(`${API}/securities/:code/bars`, ({ params, request }) => HttpResponse.json(
      bars(String(params.code), new URL(request.url).searchParams.get('freq') as BarsResponse['freq']),
    )),
    http.get(`${API}/quotes`, ({ request }) => HttpResponse.json({ items: [{
      security_code: new URL(request.url).searchParams.get('codes'), name: '示例数据证券',
      price: '10.20', change_pct: '2.00', volume: '10000', amount: '102000', t: stamp,
      data_status: 'fresh', data_as_of: stamp, gaps: [],
    }] })),
    http.get(`${API}/securities/:code/financials`, ({ params }) => HttpResponse.json({
      security_code: params.code, name: '示例数据证券', items: [], sources: [],
      data_status: 'unavailable', data_as_of: null, gaps: [],
    })),
    http.get(`${API}/horizon-assessments`, () => apiError(404)),
  );
});

function renderAt(path = '/reviews') {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

function enter(value: string) {
  const input = screen.getByLabelText('证券搜索');
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 });
}

describe('T-F41 搜索及个股页（示例数据）', () => {
  // quote 空值及真实日 K 回归统一由 pool-stock-null-quote.test.tsx 覆盖。
  it('代码段补全覆盖三所，并保留显式 ETF/指数后缀', () => {
    for (const prefix of ['300', '301', '000', '001', '002', '003']) {
      expect(completeSecurityCode(`${prefix}001`)).toBe(`${prefix}001.SZ`);
    }
    for (const prefix of ['600', '601', '603', '605', '688', '689']) {
      expect(completeSecurityCode(`${prefix}001`)).toBe(`${prefix}001.SH`);
    }
    for (const bare of ['920001', '830001', '430001']) expect(completeSecurityCode(bare)).toBe(`${bare}.BJ`);
    expect(completeSecurityCode(' ３００５０２.sz ')).toBe(code);
    for (const explicit of ['510300.SH', '000001.SH']) expect(completeSecurityCode(explicit)).toBe(explicit);
    for (const invalid of ['abc', '12345', '999999', '300502.SZ/other']) expect(completeSecurityCode(invalid)).toBeNull();
  });

  it.each([
    ['300502', '300502.SZ'], ['300502.SZ', '300502.SZ'], ['000001', '000001.SZ'],
    ['600519', '600519.SH'], ['920001', '920001.BJ'],
  ])('回车 %s 不依赖搜索响应，进入 /stocks/%s', async (input, expected) => {
    const router = renderAt();
    enter(input);
    await waitFor(() => expect(router.state.location.pathname).toBe(`/stocks/${expected}`));
    expect(await screen.findByTestId('stock-head')).toHaveTextContent(expected);
    expect(router.state.errors).toBeNull();
  });

  it.each(['abc', '12345', '999999'])('%s 无匹配时给出提示并保持当前页', async (input) => {
    const router = renderAt();
    enter(input);
    expect(await screen.findByText(/请输入有效的证券代码或选择搜索结果/)).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/reviews');
    expect(router.state.errors).toBeNull();
  });

  it.each(['enter', 'click'])('当前简称的唯一结果仍支持 %s 进入个股页', async (action) => {
    server.use(http.get(`${API}/securities/search`, () => HttpResponse.json({ items: [{
      security_code: code, name: '示例数据证券', type: 'stock', exchange: 'SZ', board: 'chinext',
      listing_status: 'listed', risk_flag: null, match_kind: 'name_exact', matched_text: null, quote_missing: null,
    }], master_as_of: '2026-11-13' })));
    const router = renderAt();
    fireEvent.change(screen.getByLabelText('证券搜索'), { target: { value: '示例数据证券' } });
    const hit = await screen.findByTestId(`search-hit-${code}`, {}, { timeout: 3000 });
    if (action === 'click') fireEvent.click(hit);
    else fireEvent.keyDown(screen.getByLabelText('证券搜索'), { key: 'Enter', code: 'Enter', keyCode: 13 });
    await waitFor(() => expect(router.state.location.pathname).toBe(`/stocks/${code}`));
    expect(await screen.findByTestId('stock-head')).toHaveTextContent(code);
  });

  it('更换输入后立即回车，不使用上一输入的唯一结果', async () => {
    server.use(http.get(`${API}/securities/search`, ({ request }) => HttpResponse.json({ items:
      new URL(request.url).searchParams.get('q') === '示例数据证券' ? [{
        security_code: code, name: '示例数据证券', type: 'stock', exchange: 'SZ', board: 'chinext',
        listing_status: 'listed', risk_flag: null, match_kind: 'name_exact', matched_text: null, quote_missing: null,
      }] : [], master_as_of: '2026-11-13',
    })));
    const router = renderAt();
    fireEvent.change(screen.getByLabelText('证券搜索'), { target: { value: '示例数据证券' } });
    await screen.findByTestId(`search-hit-${code}`, {}, { timeout: 3000 });
    enter('abc');
    expect(await screen.findByText(/请输入有效的证券代码或选择搜索结果/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByTestId(`search-hit-${code}`)).not.toBeInTheDocument());
    expect(router.state.location.pathname).toBe('/reviews');
    expect(router.state.errors).toBeNull();
  });

  it.each([404, 422, 500])('搜索接口 %s 留在下拉内提示', async (status) => {
    server.use(http.get(`${API}/securities/search`, () => apiError(status)));
    const router = renderAt();
    fireEvent.change(screen.getByLabelText('证券搜索'), { target: { value: '示例数据' } });
    expect(await screen.findByTestId('search-status', {}, { timeout: 3000 })).toHaveAttribute('role', 'alert');
    expect(router.state.location.pathname).toBe('/reviews');
    expect(router.state.errors).toBeNull();
  });

  it.each([404, 422, 500])('档案接口 %s 在个股页显示错误', async (status) => {
    server.use(http.get(`${API}/securities/:code`, () => apiError(status)));
    const router = renderAt(`/stocks/${code}`);
    const page = await screen.findByTestId('stock-page');
    if (status === 404) expect(await within(page).findByText('未找到该证券')).toBeInTheDocument();
    else expect(await within(page).findByRole('alert')).toHaveTextContent('加载失败');
    expect(router.state.location.pathname).toBe(`/stocks/${code}`);
    expect(router.state.errors).toBeNull();
    expect(screen.getByLabelText('证券搜索')).toBeInTheDocument();
  });

  it.each([404, 500])('财务接口 %s 保留档案与外壳并在页内展示错误', async (status) => {
    server.use(
      http.get(`${API}/securities/:code/financials`, () => apiError(status)),
    );
    const router = renderAt(`/stocks/${code}`);
    const head = await screen.findByTestId('stock-head');
    expect(head).toHaveTextContent(code);
    const page = screen.getByTestId('stock-page');
    expect(await within(page).findByRole('alert')).toHaveTextContent('加载失败');
    expect(screen.getByTestId('profile-panel')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/stocks/${code}`);
    expect(router.state.errors).toBeNull();
    expect(screen.getByLabelText('证券搜索')).toBeInTheDocument();
  });

  it.each([404, 500])('K 线接口 %s 只在图表区域显示错误', async (status) => {
    server.use(http.get(`${API}/securities/:code/bars`, () => apiError(status)));
    const router = renderAt(`/stocks/${code}`);
    const chart = await screen.findByTestId('price-chart');
    expect(await within(chart).findByRole('alert')).toHaveTextContent('加载失败');
    expect(screen.getByTestId('stock-head')).toHaveTextContent(code);
    expect(screen.getByTestId('profile-panel')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/stocks/${code}`);
    expect(router.state.errors).toBeNull();
    expect(screen.getByLabelText('证券搜索')).toBeInTheDocument();
  });
});

// 每个合法可空字段单独置 null，避免多个缺口恰好绕过发生异常的渲染分支。
type NullableKey<T> = { [K in keyof T]-?: null extends T[K] ? K : never }[keyof T];
type NullCase = { field: string; endpoint: string; body: object; tab: string; ready: string };
function nullCases<T extends object>(endpoint: string, body: T, keys: readonly NullableKey<T>[], tab = 'financials', ready = `tab-${tab}`): NullCase[] {
  return keys.map((key) => ({ field: `${endpoint || 'profile'}.${String(key)}`, endpoint, body: { ...body, [key]: null }, tab, ready }));
}
function itemNullCases<T extends object>(endpoint: string, body: object, item: T, keys: readonly NullableKey<T>[], tab: string): NullCase[] {
  return keys.map((key) => ({ field: `${endpoint}.items[].${String(key)}`, endpoint,
    body: { ...body, items: [{ ...item, [key]: null }] }, tab, ready: `tab-${tab}` }));
}

const examplePeriod: FinancialPeriod = {
  period_end: '2026-09-30', report_period: 'q3', announce_date: '2026-10-30', available_from: '2026-10-31', is_restated: false,
  revenue: '10000', revenue_yoy_pct: '1', net_profit: '2000', net_profit_yoy_pct: '2', deducted_net_profit: '1500',
  eps: '1', bvps: '5', roe_pct: '10', gross_margin_pct: '20', debt_ratio_pct: '30', operating_cash_flow: '3000',
};
const exampleSource = { provider: 'exchange' as const, endpoint: '/example', fetched_at: stamp };
const sourced = { security_code: code, name: '示例数据证券', sources: [exampleSource], data_status: 'fresh' as const, data_as_of: stamp, gaps: [] };
const exampleFinancials: FinancialsResponse = { ...sourced, items: [examplePeriod] };
const exampleFlow: FundFlowDay = {
  trade_date: '2026-11-13', amount: '1000', main_net: '100', super_large_net: '50', large_net: '50',
  medium_net: '-20', small_net: '-80', main_net_pct: '10', is_final: true,
};
const exampleFlows: FundFlowsResponse = { ...sourced, items: [exampleFlow] };
const exampleFactor: FactorValue = {
  factor_id: 'example-factor', feature_key: 'example-feature', name: '示例数据因子', category: 'valuation',
  value: '10', unit: '倍', market_rank: 1, market_rank_pct: '99',
};
const exampleFactors: FactorsResponse = {
  ...sourced, trade_date: '2026-11-13', factor_set_version: '示例数据版本',
  counts: { total: 1, by_category: { valuation: 1 } }, items: [exampleFactor],
};
const exampleAnnouncement: Announcement = {
  id: 'example-announcement', published_at: stamp, first_seen_at: stamp, title: '示例数据公告', category: 'other',
  category_raw: '示例数据分类', level_raw: '示例数据级别', url: 'https://www.cninfo.com.cn/example.pdf', url_host: 'www.cninfo.com.cn', file_format: 'pdf',
};
const exampleAnnouncements: AnnouncementsResponse = {
  ...sourced, items: [exampleAnnouncement], next_cursor: null,
  disclaimer: '示例数据：公告内容以交易所及上市公司披露原文为准。',
};
const exampleProfile: SecurityProfile = {
  ...securityProfile('600000.SH')!, ...sourced, exchange: 'SZ', suspended: false,
  former_names: [{ name: '示例数据旧名', until: null }], code_history: [{ security_code: '000001.SZ', until: null }],
};
const periodFields = ['announce_date', 'available_from', 'revenue', 'revenue_yoy_pct', 'net_profit', 'net_profit_yoy_pct',
  'deducted_net_profit', 'eps', 'bvps', 'roe_pct', 'gross_margin_pct', 'debt_ratio_pct', 'operating_cash_flow'] as const satisfies readonly NullableKey<FinancialPeriod>[];
const flowFields = ['amount', 'main_net', 'super_large_net', 'large_net', 'medium_net', 'small_net', 'main_net_pct'] as const satisfies readonly NullableKey<FundFlowDay>[];
const factorFields = ['feature_key', 'value', 'unit', 'market_rank', 'market_rank_pct'] as const satisfies readonly NullableKey<FactorValue>[];
const announcementFields = ['category_raw', 'level_raw', 'url', 'url_host', 'file_format'] as const satisfies readonly NullableKey<Announcement>[];
const sourceBodies = [
  { endpoint: 'financials', body: exampleFinancials, tab: 'financials' },
  { endpoint: 'fund-flows', body: exampleFlows, tab: 'fund-flow' },
  { endpoint: 'factors', body: exampleFactors, tab: 'factors' },
  { endpoint: 'announcements', body: exampleAnnouncements, tab: 'announcements' },
];
const nullableCases: NullCase[] = [
  ...nullCases('bars', bars(code, '1m'), ['pre_close', 'adjust_as_of', 'next_before', 'data_as_of']),
  ...(['pre_close', 'avg_price'] as const).map((field) => ({
    field: `bars.items[].${field}`, endpoint: 'bars', body: { ...bars(code, '1m'), items: [{ ...bars(code, '1m').items[0], [field]: null }] }, tab: 'financials', ready: 'tab-financials',
  })),
  ...nullCases('', exampleProfile, ['board', 'list_date', 'list_date_basis', 'delist_date', 'risk_flag', 'industry', 'total_shares', 'float_shares', 'suspended', 'data_as_of']),
  ...itemNullCases('financials', exampleFinancials, examplePeriod, periodFields, 'financials'),
  ...itemNullCases('fund-flows', exampleFlows, exampleFlow, flowFields, 'fund-flow'),
  ...itemNullCases('factors', exampleFactors, exampleFactor, factorFields, 'factors'),
  ...nullCases('factors', exampleFactors, ['trade_date', 'factor_set_version'], 'factors'),
  ...itemNullCases('announcements', exampleAnnouncements, exampleAnnouncement, announcementFields, 'announcements'),
  ...nullCases('announcements', exampleAnnouncements, ['next_cursor'], 'announcements'),
  ...(['security_code', 'name'] as const).map((field) => ({ field: `announcements.${field}`, endpoint: 'announcements',
    body: { ...exampleAnnouncements, [field]: null }, tab: 'announcements', ready: 'tab-announcements' })),
  ...sourceBodies.flatMap(({ endpoint, body, tab }) => [
    ...nullCases(endpoint, body, ['data_as_of'], tab),
    ...(['endpoint', 'fetched_at'] as const).map((field) => ({ field: `${endpoint}.sources[].${field}`, endpoint, tab, ready: `tab-${tab}`,
      body: { ...body, sources: [{ ...exampleSource, [field]: null }] } })),
  ]),
  ...(['endpoint', 'fetched_at'] as const).map((field) => ({ field: `profile.sources[].${field}`, endpoint: '', tab: 'financials', ready: 'tab-financials',
    body: { ...exampleProfile, sources: [{ ...exampleSource, [field]: null }] } })),
  { field: 'profile.former_names[].until', endpoint: '', body: exampleProfile, tab: 'financials', ready: 'tab-financials' },
  { field: 'profile.code_history[].until', endpoint: '', body: exampleProfile, tab: 'financials', ready: 'tab-financials' },
];

describe('T-F41 补充：逐字段 null 与页面错误边界（示例数据）', () => {
  beforeEach(() => {
    fault.realCharts = true;
    server.use(...sourceBodies.map(({ endpoint, body }) =>
      http.get(`${API}/securities/:code/${endpoint}`, () => HttpResponse.json(body))));
  });

  it.each(nullableCases)('$field=null 时完成渲染，不靠错误边界隐藏空值问题', async ({ endpoint, body, tab, ready }) => {
    let received = false;
    const url = `${API}/securities/:code${endpoint ? `/${endpoint}` : ''}`;
    server.use(http.get(url, ({ request }) => {
      received = true;
      // 同一字段也覆盖日/周 K，保持响应周期与请求一致。
      return HttpResponse.json(endpoint === 'bars' ? { ...body, freq: new URL(request.url).searchParams.get('freq') } : body);
    }));
    const router = renderAt(`/stocks/${code}?tab=${tab}`);
    await screen.findByTestId(ready);
    const head = screen.getByTestId('stock-head');
    await waitFor(() => expect(within(head).queryByText('行情加载中…')).not.toBeInTheDocument());
    fireEvent.click(screen.getByText('分时'));
    await screen.findByTestId('intraday');
    fireEvent.click(screen.getByText('日K'));
    await screen.findByTestId('kline');
    fireEvent.click(screen.getByText('周K'));
    await waitFor(() => expect(screen.getByTestId('price-chart')).toHaveTextContent('已载入 1 根周 K'));
    expect(received).toBe(true);
    expect(screen.queryByTestId('stock-render-error')).not.toBeInTheDocument();
    expect(screen.getByTestId('stock-page').textContent).not.toMatch(/NaN|undefined|\bnull\b/);
    expect(router.state.errors).toBeNull();
  });

  it('分时无 bar 且 data_as_of=null 时跳过交易日和昨收推断', async () => {
    server.use(http.get(`${API}/securities/:code/bars`, ({ request }) => {
      const freq = new URL(request.url).searchParams.get('freq') as BarsResponse['freq'];
      return HttpResponse.json({ ...bars(code, freq), items: [], data_as_of: null });
    }));
    const router = renderAt(`/stocks/${code}`);
    fireEvent.click(within(await screen.findByTestId('price-chart')).getByText('分时'));
    expect(await screen.findByTestId('chart-empty')).toHaveTextContent('无分时数据');
    const head = screen.getByTestId('stock-head');
    const row = within(head).getByText('昨收').parentElement!;
    expect(row).toHaveTextContent('—');
    expect(screen.queryByTestId('stock-render-error')).not.toBeInTheDocument();
    expect(router.state.errors).toBeNull();
  });

  it.each(['header', 'intraday', 'kline', 'financials', 'fund-flow', 'factors', 'announcements'])('%s 抛错显示页内卡片，重试重取数据并恢复', async (module) => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      fault.module = module;
      const tab = ['fund-flow', 'factors', 'announcements'].includes(module) ? module : 'financials';
      const router = renderAt(`/stocks/${code}?tab=${tab}`);
      if (module === 'intraday') {
        await screen.findByTestId('kline');
        fireEvent.click(screen.getByText('分时'));
      }
      const card = await screen.findByTestId('stock-render-error');
      expect(card).toHaveAttribute('role', 'alert');
      expect(card).toHaveTextContent('个股页暂时无法显示');
      expect(screen.queryByText(/Unexpected Application Error/)).not.toBeInTheDocument();
      expect(screen.getByLabelText('证券搜索')).toBeInTheDocument();
      expect(router.state.errors).toBeNull();
      let refetched = false;
      server.use(http.get(`${API}/securities/:code`, () => {
        refetched = true;
        return HttpResponse.json(exampleProfile);
      }));
      fault.module = '';
      fireEvent.click(within(card).getByRole('button', { name: /重\s*试/ }));
      await screen.findByTestId(`tab-${tab}`);
      await waitFor(() => expect(refetched).toBe(true));
      expect(screen.getByTestId('stock-head')).toHaveTextContent(code);
      expect(screen.queryByTestId('stock-render-error')).not.toBeInTheDocument();
      expect(router.state.errors).toBeNull();
    } finally { log.mockRestore(); }
  });

  it('错误卡片期间切换证券自动恢复新页面', async () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    try {
      fault.module = 'header';
      const router = renderAt(`/stocks/${code}`);
      await screen.findByTestId('stock-render-error');
      fault.module = '';
      enter('600519');
      expect(await screen.findByTestId('stock-head')).toHaveTextContent('600519.SH');
      expect(router.state.errors).toBeNull();
    } finally { log.mockRestore(); }
  });
});
