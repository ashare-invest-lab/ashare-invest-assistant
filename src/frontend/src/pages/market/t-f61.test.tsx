import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Bar, MarketBasis, MarketOverview } from '../../api/types';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { MARKET_OVERVIEW } from '../../mocks/marketFixtures';
import { server } from '../../mocks/server';
import { preloadRoutes } from '../../test/preloadRoutes';

// 只替换绘图库边界；真实页面、路由、查询、周期切换及缺口展示均参与测试。
vi.mock('../../components/charts/IntradayChart', () => ({ IntradayChart: ({ bars, empty }: { bars: Bar[]; empty: React.ReactNode }) => <div data-testid="minute-bars">{bars.length ? JSON.stringify(bars) : empty}</div> }));
vi.mock('../../components/charts/KlineChart', () => ({ KlineChart: ({ bars }: { bars: Bar[] }) => <div data-testid="daily-bars">{JSON.stringify(bars)}</div> }));

const marketRoutes = routes.flatMap((r) => r.children ?? []).filter((r) => r.path === 'market' || r.path === 'market/overview');
beforeAll(() => preloadRoutes(marketRoutes));
const paths = ['/market', '/market/overview'];
const basis: MarketBasis = {
  snapshot_id: '00000000-0000-4000-8000-000000000061', observed_date: '2026-11-02', mode: 'intraday', scope: '沪深股票口径',
  eligible: 10, observed: 10, trading: 8, suspended: 2, missing: 0, source: '合成夹具（未验证）',
};
const base: MarketOverview = { ...MARKET_OVERVIEW, basis, indices: [], trade_date: '2026-11-02' };
function mount(path: string, body: unknown) {
  server.use(http.get('/api/v1/market/overview', () => HttpResponse.json(body as MarketOverview)));
  return render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={createMemoryRouter(marketRoutes, { initialEntries: [path] })} /></AppProviders>);
}
const cases: [string, MarketOverview, string, boolean, boolean][] = [
  ['同批', base, '覆盖率：100.0%', false, false],
  ['部分批', { ...base, data_status: 'partial', breadth: null, turnover_total: null, basis: { ...basis, observed: 8, missing: 2 }, gaps: [{ key: 'market.breadth', reason: 'no_source', message: '合成：缺两个成员' }] }, 'missing：2', true, false],
  ['旧收盘', { ...base, data_status: 'stale', basis: { ...basis, observed_date: '2026-10-30', mode: 'close' } }, 'observed_date：2026-10-30', false, true],
  ['旧且部分', { ...base, data_status: 'partial', basis: { ...basis, observed_date: '2026-10-30', missing: 2, observed: 8 } }, 'missing：2', true, true],
  ['真实零', { ...base, breadth: { up: 0, down: 0, flat: 0, limit_up: 0, limit_down: 0 }, basis: { ...basis, eligible: 0, observed: 0, trading: 0, suspended: 0 } }, '覆盖率：—', false, false],
  ['未知资格池', { ...base, basis: { ...basis, eligible: null, observed: null, trading: null, suspended: null, missing: null } }, 'eligible：—', false, false],
  ['旧响应', { ...base, basis: undefined }, 'basis：—', false, false],
  ['全空', { ...base, basis: null, breadth: null, turnover_total: null, data_status: 'unavailable', data_as_of: null, gaps: [{ key: 'market.breadth', reason: 'no_source', message: '合成：无市场批次' }] }, 'basis：—', false, false],
];

describe.each(paths)('%s 共用市场展示', (path) => {
  it.each(cases)('%s', async (_name, body, text, partial, old) => {
    const { container } = mount(path, body);
    const panel = await screen.findByTestId('market-basis');
    expect(panel).toHaveTextContent(text);
    if (body.basis?.eligible === null) expect(panel).toHaveTextContent('覆盖率：—');
    expect(!!within(panel).queryByText('部分批')).toBe(partial);
    expect(!!within(panel).queryByText('旧批')).toBe(old);
    if (body.basis) expect(panel).toHaveTextContent(body.basis.source!);
    if (body.gaps.length) expect(screen.getByTestId('market-gap-note')).toHaveTextContent(body.gaps[0].message);
    const breadth = screen.getByTestId('breadth-panel');
    if (!body.breadth) expect(breadth).toHaveTextContent('涨跌家数暂不可用');
    if (body.basis?.eligible === 0) {
      expect(breadth.querySelector('.breadth-bar')).toBeNull();
      expect(breadth).toHaveTextContent('上涨占比—');
      expect(breadth).toHaveTextContent('涨停0');
    }
    expect(container.innerHTML).not.toMatch(/NaN|Infinity|undefined/);
  });

  it.each(['__proto__', 'constructor', 'future_value'])('枚举白名单拒绝 %s', async (value) => {
    server.use(http.get('/api/v1/market/sector-flows', () => HttpResponse.json({ kind: 'industry', taxonomy: value, trade_date: null, items: [], sources: [], data_status: value, data_as_of: null, gaps: [{ key: 'sector_flows', reason: value, message: '合成未知板块' }] })));
    mount(path, { ...base, session: value, regime: value, data_status: value, basis: { ...basis, mode: value }, gaps: [{ key: 'market.breadth', reason: value, message: '合成未知原因' }] });
    const panel = await screen.findByTestId('market-basis');
    expect(panel).toHaveTextContent('mode：未知');
    expect(screen.getByTestId('regime-panel')).toHaveTextContent('市场状态 未知');
    expect(screen.getByTestId('market-gap-note')).toHaveTextContent('未知（合成未知原因）');
    const status = screen.getAllByText('未知').find((el) => el.className.includes('ds-tag'));
    expect(status).toHaveStyle({ color: '#8c8c8c' });
    expect(await screen.findByText('暂无板块资金：未知')).toBeInTheDocument();
    expect(screen.getByTestId('sector-meta')).toHaveTextContent('未知');
  });

  it('稀疏 1m 原样传图，不插值或补零', async () => {
    const bars: Bar[] = ['09:31', '09:33'].map((t) => ({ t: `2026-11-02T${t}:00+08:00`, open: '10', high: '11', low: '9', close: '10', pre_close: null, volume: '1', amount: '10', avg_price: null, is_final: true }));
    server.use(http.get('/api/v1/securities/:code/bars', () => HttpResponse.json({ security_code: '000001.SH', name: '合成指数', freq: '1m', adjust: 'none', items: bars, pre_close: null, next_before: null, adjust_as_of: null, data_status: 'partial', data_as_of: bars[0].t, gaps: [{ key: 'bars', reason: '__proto__', message: '合成：缺 09:32' }] })));
    mount(path, { ...base, indices: MARKET_OVERVIEW.indices.slice(0, 1) });
    expect(await screen.findByTestId('minute-bars')).toHaveTextContent(JSON.stringify(bars));
    expect(screen.getByTestId('chart-gap-note')).toHaveTextContent('未知（合成：缺 09:32）');
  });

  it('缺少 1m 不从日 K 造数，切回分时仍为空', async () => {
    const requested: string[] = [];
    const daily: Bar = { t: '2026-10-30', open: '10', high: '11', low: '9', close: '10', pre_close: null, volume: '1', amount: '10', avg_price: null, is_final: true };
    server.use(http.get('/api/v1/securities/:code/bars', ({ request }) => {
      const freq = new URL(request.url).searchParams.get('freq')!;
      requested.push(freq);
      return HttpResponse.json({ security_code: '000001.SH', name: '合成指数', freq, adjust: freq === '1m' ? 'none' : 'qfq', items: freq === '1m' ? [] : [daily], next_before: null, pre_close: null, adjust_as_of: null,
        data_status: freq === '1m' ? 'unavailable' : 'fresh', data_as_of: freq === '1m' ? null : '2026-10-30T15:00:00+08:00', gaps: freq === '1m' ? [{ key: 'bars', reason: 'no_source', message: '合成：缺少 1m' }] : [] });
    }));
    mount(path, { ...base, indices: MARKET_OVERVIEW.indices.slice(0, 1) });
    expect(await screen.findByTestId('minute-bars')).toHaveTextContent('无分时数据');
    expect(requested).toEqual(['1m']);
    await userEvent.click(screen.getByText('日K'));
    expect(await screen.findByTestId('daily-bars')).toHaveTextContent(JSON.stringify([daily]));
    await userEvent.click(screen.getByText('分时'));
    await waitFor(() => expect(screen.getByTestId('minute-bars')).toHaveTextContent('无分时数据'));
    expect(screen.queryByTestId('daily-bars')).toBeNull();
    expect(screen.getByTestId('chart-gap-note')).toHaveTextContent('合成：缺少 1m');
    expect(requested).toEqual(['1m', 'd']);
  });
});
