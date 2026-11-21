import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { preloadRoutes } from '../../test/preloadRoutes';
import { server } from '../../mocks/server';

const API = '/api/v1';
const renderAt = (path: string) => {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
};

beforeAll(() => preloadRoutes(routes), 30_000);

describe('T-F69 复盘页面', () => {
  it('显示列表并能进入详情', async () => {
    const user = userEvent.setup();
    const router = renderAt('/reviews');
    expect(await screen.findByTestId('reviews-page')).toBeInTheDocument();
    expect(await screen.findByTestId('review-link-review-example-1')).toHaveTextContent('600000.SH');
    await user.click(screen.getByTestId('review-link-review-example-1'));
    await waitFor(() => expect(router.state.location.pathname).toBe('/reviews/review-example-1'));
    await screen.findByText(/先记录执行条件/);
    expect(screen.getByTestId('review-detail')).toBeInTheDocument();
    expect(screen.getByTestId('review-notes')).toHaveTextContent('先记录执行条件');
    expect(screen.getByTestId('metric-holding_return')).toHaveTextContent('—');
    expect(screen.getByTestId('review-metric-gap')).toHaveTextContent('无数据源');
  });

  it('按证券和计划筛选并写入 URL', async () => {
    const user = userEvent.setup();
    const router = renderAt('/reviews');
    await screen.findByTestId('review-link-review-example-1');
    await user.type(screen.getByLabelText('证券代码筛选'), '600000.SH');
    await waitFor(() => expect(router.state.location.search).toContain('security_code=600000.SH'));
    await user.clear(screen.getByLabelText('计划筛选'));
    await user.type(screen.getByLabelText('计划筛选'), 'plan-example-1');
    await waitFor(() => expect(router.state.location.search).toContain('plan_id=plan-example-1'));
  });

  it('支持空列表与创建校验，合法提交后进入详情', async () => {
    const user = userEvent.setup();
    server.use(http.get(`${API}/reviews`, () => HttpResponse.json({ items: [], next_cursor: null })));
    renderAt('/reviews');
    expect(await screen.findByText('暂无复盘记录')).toBeInTheDocument();
    await user.click(screen.getByTestId('new-review'));
    await user.click(screen.getByTestId('submit-review'));
    expect(await screen.findByTestId('review-form-error')).toHaveTextContent('至少填写一项');
    await user.type(screen.getByLabelText('证券代码'), '600001.SH');
    await user.type(screen.getByLabelText('起始日期'), '2026-11-20');
    await user.type(screen.getByLabelText('结束日期'), '2026-11-01');
    await user.click(screen.getByTestId('submit-review'));
    expect(await screen.findByTestId('review-form-error')).toHaveTextContent('日期必须有序');
    await user.clear(screen.getByLabelText('结束日期'));
    await user.type(screen.getByLabelText('结束日期'), '2026-11-30');
    await user.type(screen.getByLabelText('复盘笔记'), '新建笔记');
    await user.click(screen.getByTestId('submit-review'));
    await screen.findByText('新建笔记');
    expect(screen.getByTestId('review-detail')).toHaveTextContent('新建笔记');
  });

  it('版本切换及未知 timeline kind、状态安全显示为未知', async () => {
    const user = userEvent.setup();
    const version = (no: number, lessons: string) => ({
      id: `v-${no}`, review_id: 'review-unknown', version_no: no, plan_version_ids: [], trade_ids: [], snapshot_id: null,
      lessons, tags: [], attribution: { judgement: [], execution: [], market: [] },
      outcome_metrics: { holding_return: { value: null, n: 0, window: 'x', small_sample: true }, benchmark_return: { value: null, n: 0, window: 'x', small_sample: true }, excess_return: { value: null, n: 0, window: 'x', small_sample: true }, max_drawdown: { value: null, n: 0, window: 'x', small_sample: true } },
      created_at: '2026-11-20T10:00:00+08:00', data_status: '__proto__', data_as_of: null, gaps: [{ key: 'x', reason: 'constructor', message: '未知状态示例' }],
    });
    const v1 = version(1, '旧版本笔记');
    const v2 = version(2, '当前版本笔记');
    const body = { id: 'review-unknown', plan_id: null, security_code: '600000.SH', name: '示例银行', period_start: '2026-11-01', period_end: '2026-11-20', current_version_no: 2, created_at: v2.created_at, data_status: '__proto__', data_as_of: null, gaps: v2.gaps, current_version: v2, versions: [v1, v2], timeline: [{ kind: '__proto__', at: v2.created_at, resource_id: null, version_no: 2, evidence_ids: [] }, { kind: 'constructor', at: v2.created_at, resource_id: null, version_no: null, evidence_ids: [] }] };
    server.use(
      http.get(`${API}/reviews/review-unknown`, () => HttpResponse.json(body)),
      http.get(`${API}/reviews/review-unknown/versions`, () => HttpResponse.json({ items: [v1, v2], next_cursor: null })),
    );
    renderAt('/reviews/review-unknown');
    await screen.findByText('当前版本笔记');
    const page = screen.getByTestId('review-detail');
    expect(within(page).getAllByText('未知').length).toBeGreaterThan(0);
    expect(within(page).getByText('当前版本笔记')).toBeInTheDocument();
    await user.click(screen.getByTestId('review-version-1'));
    expect(screen.getByTestId('review-notes')).toHaveTextContent('旧版本笔记');
  });
});

