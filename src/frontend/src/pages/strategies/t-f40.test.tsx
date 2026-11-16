import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { STRATEGY_TEMPLATES, trackingOf } from '../../mocks/strategyHandlers';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { preloadRoutes } from '../../test/preloadRoutes';

vi.mock('../../components/charts/KlineChart', () => ({ KlineChart: () => <div data-testid="kline" /> }));
vi.mock('../../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="intraday" /> }));
vi.mock('../../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div data-testid="fund-flow-chart" /> }));

beforeAll(() => preloadRoutes(routes), 60_000);
beforeEach(() => mockLoginAs('demo_user'));
afterEach(() => server.resetHandlers());

const API = '/api/v1';
function renderAt(path: string) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

const template = (key: string) => STRATEGY_TEMPLATES.find((item) => item.key === key)!;

describe('T-F40 策略详情', () => {
  it('t-f40 打开已有模板详情并展示版本配置与跟踪表', async () => {
    const item = template('st_pullback_ma');
    renderAt(`/strategies/${item.id}`);
    expect(await screen.findByTestId('strategy-detail-page')).toBeInTheDocument();
    expect(await screen.findByText(item.name)).toBeInTheDocument();
    expect(screen.getByText(item.key)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`当前版本：v${item.current_version.version_no}`))).toBeInTheDocument();
    expect(screen.getByText(/已发布|观察中|模拟中/)).toBeInTheDocument();
    expect(await screen.findByText('示例数据-param-hash')).toBeInTheDocument();
    expect(screen.getByText('示例数据-R1')).toBeInTheDocument();
    expect(screen.getByText('参数定义')).toBeInTheDocument();
    expect(screen.getByText('ma_fast')).toBeInTheDocument();
    expect(await screen.findByTestId('strategy-tracking-stats')).toBeInTheDocument();
    expect(screen.getByTestId('track-1')).toBeInTheDocument();
  });

  it('t-f40 高风险模板显示高风险标记', async () => {
    const item = template('st_strong_momo');
    renderAt(`/strategies/${item.id}`);
    expect(await screen.findByText('高风险')).toBeInTheDocument();
  });

  it('t-f40 从策略库点击模板名称进入详情', async () => {
    const item = template('st_pullback_ma');
    renderAt('/strategies');
    const link = await screen.findByRole('link', { name: item.name });
    expect(link).toHaveAttribute('href', `/strategies/${item.id}`);
    fireEvent.click(link);
    expect(await screen.findByTestId('strategy-detail-page')).toBeInTheDocument();
    expect(await screen.findByText('示例数据-param-hash')).toBeInTheDocument();
  });

  it('t-f40 未知 id 显示列表空态且不请求版本接口', async () => {
    let versionCalls = 0;
    server.use(http.get(`${API}/strategies/:id/versions/:vid`, () => { versionCalls++; return HttpResponse.json({}); }));
    renderAt('/strategies/unknown-example-id');
    expect(await screen.findByText('策略列表中没有该模板')).toBeInTheDocument();
    expect(versionCalls).toBe(0);
  });

  it('t-f40 列表接口 500 显示加载失败而非空列表', async () => {
    server.use(http.get(`${API}/strategies`, () => HttpResponse.json({ error: { code: 'INTERNAL_ERROR', message: '示例数据：列表失败', details: null } }, { status: 500 })));
    renderAt(`/strategies/${template('st_pullback_ma').id}`);
    expect(await screen.findByText(/策略列表加载失败/)).toBeInTheDocument();
    expect(screen.queryByText('策略列表中没有该模板')).toBeNull();
  });

  it('t-f40 版本接口 404 保留模板名并显示版本加载失败', async () => {
    const item = template('st_pullback_ma');
    server.use(http.get(`${API}/strategies/:id/versions/:vid`, () => HttpResponse.json({ error: { code: 'NOT_FOUND', message: '示例数据：版本不存在', details: null } }, { status: 404 })));
    renderAt(`/strategies/${item.id}`);
    expect(await screen.findByText(item.name)).toBeInTheDocument();
    expect(await screen.findByText(/策略版本加载失败/)).toBeInTheDocument();
    expect(screen.queryByText('策略列表中没有该模板')).toBeNull();
  });

  it('t-f40 切换全站请求 site scope 且继续显示跟踪统计', async () => {
    const item = template('st_pullback_ma');
    const scopes: string[] = [];
    server.use(http.get(`${API}/strategies/:id/versions/:vid/tracking`, ({ request }) => {
      const scope = new URL(request.url).searchParams.get('scope') ?? 'mine';
      scopes.push(scope);
      return HttpResponse.json(trackingOf(item, scope as 'mine' | 'site'));
    }));
    renderAt(`/strategies/${item.id}`);
    expect(await screen.findByTestId('strategy-tracking-stats')).toBeInTheDocument();
    fireEvent.click(screen.getByText('全站'));
    await waitFor(() => expect(scopes).toContain('site'));
    expect(screen.getByTestId('strategy-tracking-stats')).toBeInTheDocument();
  });

  it('t-f40 截断列表不含模板时显示暂无法打开详情', async () => {
    const item = template('st_pullback_ma');
    let pages = 0;
    server.use(http.get(`${API}/strategies`, () => {
      pages += 1;
      return HttpResponse.json({ items: [], next_cursor: `示例数据-cursor-${pages}` });
    }));
    renderAt(`/strategies/${item.id}`);
    expect(await screen.findByText('已加载列表中没有该模板，暂时无法打开详情。')).toBeInTheDocument();
  });

  it('t-f40 demo_t 跟踪样本不足时显示样本不足提示', async () => {
    const item = template('demo_t');
    renderAt(`/strategies/${item.id}`);
    const stats = await screen.findByTestId('strategy-tracking-stats');
    expect(within(stats).getAllByText(/样本不足/).length).toBeGreaterThan(0);
  });
});
