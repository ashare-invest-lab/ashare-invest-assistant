/** T-F41 回归：以下 MSW 响应均为示例数据，不连接真实行情源。 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { BarsResponse, QuoteItem } from '../api/types';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { securityProfile } from '../mocks/marketFixtures';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { completeSecurityCode } from '../lib/securityCode';
import { preloadRoutes } from './preloadRoutes';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div /> }));

const API = '/api/v1';
const stamp = '2026-11-13T15:00:00+08:00';
const code = '300502.SZ';
const gap = { key: 'quotes', reason: 'no_source' as const, message: '示例数据：本人行情缓存尚无可用读取源' };

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
  it.each(['d', '1m', 'empty'] as const)('空行情时间与 %s K 线共存时保持个股页，不触发路由报错页', async (available) => {
    // 复刻后端 GET /quotes 的合法无源响应；不把空时间或空价格伪造为当前值。
    const quote: QuoteItem = {
      security_code: code, name: '示例数据证券', price: null, change_pct: null, volume: null, amount: null,
      t: null, data_status: 'unavailable', data_as_of: null, gaps: [gap],
    };
    server.use(
      http.get(`${API}/quotes`, () => HttpResponse.json({ items: [quote] })),
      http.get(`${API}/securities/:code/bars`, ({ request }) => {
        const freq = new URL(request.url).searchParams.get('freq') as BarsResponse['freq'];
        const data = bars(code, freq);
        return HttpResponse.json(available === freq ? data : { ...data, items: [], pre_close: null, data_as_of: null });
      }),
    );
    const router = renderAt(`/stocks/${code}`);
    const head = await screen.findByTestId('stock-head');
    await waitFor(() => expect(within(head).getByTestId('quote-gap-note')).toHaveTextContent(gap.message));
    expect(await screen.findByTestId('intraday')).toBeInTheDocument();
    expect(head).toHaveTextContent('暂无行情数据');
    expect(head.textContent).not.toMatch(/NaN|null|undefined|0手|0\.00亿/);
    expect(router.state.location.pathname).toBe(`/stocks/${code}`);
    expect(router.state.errors).toBeNull();
    expect(screen.getByLabelText('证券搜索')).toBeInTheDocument();
  });

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

  it.each([404, 500])('财务和行情接口 %s 保留档案与外壳并在页内展示错误', async (status) => {
    server.use(
      http.get(`${API}/securities/:code/financials`, () => apiError(status)),
      http.get(`${API}/quotes`, () => apiError(status)),
    );
    const router = renderAt(`/stocks/${code}`);
    const head = await screen.findByTestId('stock-head');
    expect(await within(head).findByRole('alert')).toHaveTextContent('加载失败');
    const page = screen.getByTestId('stock-page');
    await waitFor(() => expect(within(page).getAllByRole('alert')).toHaveLength(2));
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

  it('行情时间缺失时提示未知，零成交量和零涨跌幅仍如实显示', async () => {
    const quote: QuoteItem = {
      security_code: code, name: '示例数据证券', price: '10.20', change_pct: '0.00', volume: '0', amount: '0',
      t: null, data_status: 'partial', data_as_of: null, gaps: [gap],
    };
    server.use(http.get(`${API}/quotes`, () => HttpResponse.json({ items: [quote] })));
    const router = renderAt(`/stocks/${code}`);
    const head = await screen.findByTestId('stock-head');
    expect(await within(head).findByText('行情时间未知')).toBeInTheDocument();
    expect(head).toHaveTextContent('(0.00%)');
    expect(head).toHaveTextContent('0手');
    expect(head).not.toHaveTextContent('NaN');
    expect(router.state.errors).toBeNull();
  });
});
