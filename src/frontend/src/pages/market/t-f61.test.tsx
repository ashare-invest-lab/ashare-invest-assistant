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
const basis: MarketBasis = { ...MARKET_OVERVIEW.basis!, eligible: 3, observed: 3, trading: 3, suspended: 0, missing: 0 };
const base: MarketOverview = { ...MARKET_OVERVIEW, basis, indices: [], trade_date: '2026-11-02', data_status: 'fresh', gaps: [] };
const chartIndex = MARKET_OVERVIEW.indices[0];
type MarketCaseBody = MarketOverview | Omit<MarketOverview, 'basis'>;
function withoutBasis(body: MarketOverview): Omit<MarketOverview, 'basis'> {
  const copy = { ...body } as Partial<MarketOverview>;
  delete copy.basis;
  return copy as Omit<MarketOverview, 'basis'>;
}
function mount(path: string, body: unknown) {
  server.use(http.get('/api/v1/market/overview', () => HttpResponse.json(body as MarketOverview)));
  return render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={createMemoryRouter(marketRoutes, { initialEntries: [path] })} /></AppProviders>);
}
const cases: [string, MarketCaseBody, string, boolean, boolean, boolean][] = [
  ['同批', base, '覆盖率：100.0%', false, false, false],
  ['部分批', { ...base, data_status: 'partial', breadth: null, turnover_total: null, basis: { ...basis, observed: 8, missing: 2 }, gaps: [{ key: 'market.breadth', reason: 'no_source', message: '合成：缺两个成员' }] }, 'missing：2', true, false, false],
  ['部分缺失', { ...base, basis: { ...basis, observed: null, suspended: null, missing: null } }, '覆盖率：—', false, false, false],
  ['旧收盘', { ...base, data_status: 'stale', basis: { ...basis, observed_date: '2026-10-30', mode: 'close' } }, 'observed_date：2026-10-30', false, true, false],
  ['旧且部分', { ...base, data_status: 'partial', basis: { ...basis, observed_date: '2026-10-30', missing: 2, observed: 8 } }, 'missing：2', true, true, false],
  ['真实零', { ...base, breadth: { up: 0, down: 0, flat: 0, limit_up: 0, limit_down: 0, up_ratio: null, down_ratio: null, flat_ratio: null }, basis: { ...basis, eligible: 0, observed: 0, trading: 0, suspended: 0 } }, '覆盖率：—', false, false, false],
  ['未知资格池', { ...base, basis: { ...basis, eligible: null, observed: null, trading: null, suspended: null, missing: null } }, 'eligible：—', false, false, false],
  ['旧响应缺失 basis', withoutBasis(base), 'basis：—', false, false, true],
  ['无市场快照', { ...base, basis: null, breadth: null, turnover_total: null, data_status: 'unavailable', data_as_of: null, gaps: [{ key: 'market.breadth', reason: 'no_source', message: '合成：无市场批次' }] }, 'basis：—', false, false, true],
];

describe.each(paths)('%s 共用市场展示', (path) => {
  it.each(cases)('%s', async (_name, body, text, partial, old, missingBasis) => {
    const { container } = mount(path, body);
    const panel = await screen.findByTestId('market-basis');
    expect(panel).toHaveTextContent(text);
    const responseBasis = 'basis' in body ? body.basis : undefined;
    if (responseBasis?.eligible === null) expect(panel).toHaveTextContent('覆盖率：—');
    if (responseBasis?.mode === 'intraday') expect(panel).toHaveTextContent('mode：intraday');
    if (responseBasis?.mode === 'close') expect(panel).toHaveTextContent('mode：close');
    if (responseBasis) expect(panel).toHaveTextContent('scope：沪深股票口径');
    if (missingBasis) {
      expect(panel).toHaveTextContent('无市场快照证据');
      expect(panel).toHaveTextContent('basis：—');
    }
    expect(!!within(panel).queryByText('部分批')).toBe(partial);
    expect(!!within(panel).queryByText('旧批')).toBe(old);
    if (responseBasis) expect(panel).toHaveTextContent(responseBasis.source!);
    if (body.gaps.length) expect(screen.getByTestId('market-gap-note')).toHaveTextContent(body.gaps[0].message);
    const breadth = screen.getByTestId('breadth-panel');
    if (!body.breadth) expect(breadth).toHaveTextContent('涨跌家数暂不可用');
    if (responseBasis?.eligible === 0) {
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
    expect(screen.getByTestId('market-page')).toHaveTextContent('未知');
    expect(await screen.findByText('暂无板块资金：未知')).toBeInTheDocument();
    expect(screen.getByTestId('sector-meta')).toHaveTextContent('未知');
  });

  it('涨跌停或计数为 null 时显示破折号并保留缺口说明', async () => {
    mount(path, {
      ...base,
      breadth: { ...base.breadth!, limit_up: null, limit_down: null, up: null, down: null, flat: null },
      gaps: [
        { key: 'market.breadth.limit_counts', reason: 'no_source', message: '合成：无涨跌停来源' },
        { key: 'market.breadth', reason: 'no_source', message: '合成：缺少涨跌家数' },
      ],
    });
    const panel = await screen.findByTestId('breadth-panel');
    expect(panel).toHaveTextContent('涨停—');
    expect(panel).toHaveTextContent('跌停—');
    expect(panel).toHaveTextContent(/上涨\s*—/);
    expect(panel).toHaveTextContent(/平盘\s*—/);
    expect(panel).toHaveTextContent(/下跌\s*—/);
    expect(screen.getByTestId('market-gap-note')).toHaveTextContent('合成：无涨跌停来源');
    expect(panel.querySelector('.breadth-bar')).not.toBeNull();
  });

  it('上涨占比直接采用后端比例，不按计数自算', async () => {
    mount(path, { ...base, breadth: { ...base.breadth!, up: 9000, down: 500, flat: 500, up_ratio: '0.2500' } });
    const panel = await screen.findByTestId('breadth-panel');
    expect(panel).toHaveTextContent('上涨占比25.0%');
  });

  it('计数部分缺失时仍按完整比例绘制条形', async () => {
    mount(path, { ...base, breadth: { ...base.breadth!, up: null } });
    const panel = await screen.findByTestId('breadth-panel');
    expect(panel).toHaveTextContent(/上涨\s*—/);
    expect(panel).toHaveTextContent('平盘 0');
    expect(panel).toHaveTextContent('下跌 1');
    expect(panel).toHaveTextContent('上涨占比66.7%');
    expect(panel.querySelector('.breadth-bar')).not.toBeNull();
  });

  it('比例缺失时不显示上涨占比或条形', async () => {
    mount(path, { ...base, breadth: { ...base.breadth!, up_ratio: null } });
    const panel = await screen.findByTestId('breadth-panel');
    expect(panel).toHaveTextContent('上涨占比—');
    expect(panel.querySelector('.breadth-bar')).toBeNull();
  });

  it('稀疏 1m 原样传图，不插值或补零', async () => {
    const bars: Bar[] = ['09:31', '09:33'].map((t) => ({ t: `2026-11-02T${t}:00+08:00`, open: '10', high: '11', low: '9', close: '10', pre_close: null, volume: '1', amount: '10', avg_price: null, is_final: true }));
    server.use(http.get('/api/v1/securities/:code/bars', () => HttpResponse.json({ security_code: chartIndex.security_code, name: chartIndex.name, freq: '1m', adjust: 'none', items: bars, pre_close: null, next_before: null, adjust_as_of: null, data_status: 'partial', data_as_of: bars[0].t, gaps: [{ key: 'bars', reason: '__proto__', message: '合成：缺 09:32' }] })));
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
      return HttpResponse.json({ security_code: chartIndex.security_code, name: chartIndex.name, freq, adjust: freq === '1m' ? 'none' : 'qfq', items: freq === '1m' ? [] : [daily], next_before: null, pre_close: null, adjust_as_of: null,
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
