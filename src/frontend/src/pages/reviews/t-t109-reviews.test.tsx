/** T-T109 / T-F69：复盘页离线契约测试。导入失败必须暴露，尚未实现的页面逐条标记待实现。 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import type { ComponentType } from 'react';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { preloadRoutes } from '../../test/preloadRoutes';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';

const API = '/api/v1';
const REVIEW_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const PLAN_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

const pageLoaders = import.meta.glob<Record<string, unknown>>('./ReviewsPage.{tsx,ts}', { eager: false });
const detailLoaders = import.meta.glob<Record<string, unknown>>('./ReviewDetailPage.{tsx,ts}', { eager: false });
const pageLoader = Object.values(pageLoaders)[0] as (() => Promise<Record<string, unknown>>) | undefined;
const detailLoader = Object.values(detailLoaders)[0] as (() => Promise<Record<string, unknown>>) | undefined;
const reviewModule = pageLoader ? await pageLoader() : null;
const detailModule = detailLoader ? await detailLoader() : null;
if (pageLoader && !(reviewModule?.ReviewsPage ?? reviewModule?.default)) {
  throw new Error('ReviewsPage 文件存在但未导出 ReviewsPage');
}
if (detailLoader && !(detailModule?.ReviewDetailPage ?? detailModule?.default)) {
  throw new Error('ReviewDetailPage 文件存在但未导出 ReviewDetailPage');
}
const ReviewsPage = (reviewModule?.ReviewsPage ?? reviewModule?.default) as ComponentType | undefined;
const ReviewDetailPage = (detailModule?.ReviewDetailPage ?? detailModule?.default) as ComponentType | undefined;

beforeAll(() => preloadRoutes(routes), 30_000);

const emptyMetric = { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true };
const metrics = {
  holding_return: emptyMetric,
  benchmark_return: emptyMetric,
  excess_return: emptyMetric,
  max_drawdown: emptyMetric,
};
const metricGaps = [
  { key: 'outcome_metrics.holding_return', reason: 'no_source', message: '定稿前无来源' },
  { key: 'outcome_metrics.benchmark_return', reason: 'no_source', message: '定稿前无来源' },
  { key: 'outcome_metrics.excess_return', reason: 'no_source', message: '定稿前无来源' },
  { key: 'outcome_metrics.max_drawdown', reason: 'no_source', message: '定稿前无来源' },
];

function versionOf(versionNo: number, lessons: string) {
  return {
    id: `v-${versionNo}`,
    review_id: REVIEW_ID,
    version_no: versionNo,
    plan_version_ids: [] as string[],
    trade_ids: [] as string[],
    snapshot_id: null,
    lessons,
    tags: [] as string[],
    attribution: { judgement: [], execution: [], market: [] },
    outcome_metrics: metrics,
    created_at: versionNo === 1 ? '2026-11-10T09:00:00+08:00' : '2026-11-20T09:00:00+08:00',
    data_status: 'partial',
    data_as_of: null,
    gaps: metricGaps,
  };
}

const version1 = versionOf(1, '旧版虚构笔记');
const version2 = versionOf(2, '虚构复盘笔记');
const review = {
  id: REVIEW_ID,
  plan_id: PLAN_ID,
  security_code: 'SYN001.SH',
  name: '虚构证券',
  period_start: '2026-11-01',
  period_end: '2026-11-20',
  current_version_no: 2,
  created_at: '2026-11-20T09:00:00+08:00',
  data_status: 'partial',
  data_as_of: null,
  gaps: metricGaps,
  current_version: version2,
  timeline: [],
  evidence: [],
};

function installList(items: unknown[] = [review]) {
  server.use(http.get(`${API}/reviews`, () => HttpResponse.json({ items, next_cursor: null })));
}

function installDetail(body: unknown = review, versionItems: unknown[] = [version1, version2]) {
  server.use(
    http.get(`${API}/reviews/${REVIEW_ID}`, () => HttpResponse.json(body as Record<string, unknown>)),
    http.get(`${API}/reviews/${REVIEW_ID}/versions`, () => HttpResponse.json({ items: versionItems, next_cursor: null })),
  );
}

function renderList(path = '/reviews') {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

function renderDetail(path = `/reviews/${REVIEW_ID}`) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

beforeEach(() => {
  mockLoginAs('demo_user');
  installList([]);
});

const reviewsRoute = routes.find((item) => item.path === '/')?.children?.find((item) => item.path === 'reviews');
const detailRoute = routes.find((item) => item.path === '/')?.children?.find((item) => item.path === 'reviews/:id');

it('/reviews 路由已登记并完成初始化，主线占位状态可观察', async () => {
  expect(reviewsRoute).toBeDefined();
  const router = renderList();
  await waitFor(() => expect(router.state.initialized).toBe(true));
  if (ReviewsPage) {
    expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();
  } else {
    expect(await screen.findByTestId('placeholder')).toBeInTheDocument();
  }
});

it.skipIf(!ReviewsPage)('/reviews 必须使用 ReviewsPage 而非占位（主线尚未提供 ReviewsPage，当前为 PlaceholderPage）', async () => {
  renderList();
  expect(await screen.findByTestId('reviews-page')).toBeInTheDocument();
  expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();
});

it.skipIf(!ReviewsPage)('空列表显示空态（主线尚未提供 ReviewsPage，待实现）', async () => {
    installList([]);
    renderList();
    expect(await screen.findByRole('status', { name: '暂无复盘记录' })).toBeInTheDocument();
});

it.skipIf(!ReviewsPage)('有数据能显示证券与计划，筛选参数随 GET 和 URL 保留（主线尚未提供 ReviewsPage，待实现）', async () => {
    const seen: URL[] = [];
    server.use(http.get(`${API}/reviews`, ({ request }) => {
      const url = new URL(request.url);
      seen.push(url);
      return HttpResponse.json({ items: [review], next_cursor: null });
    }));
    const router = renderList(`/reviews?security_code=SYN001.SH&plan_id=${PLAN_ID}`);
    expect(await screen.findByText('SYN001.SH')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(PLAN_ID))).toBeInTheDocument();
    await waitFor(() => expect(seen.some((url) => url.searchParams.get('security_code') === 'SYN001.SH' && url.searchParams.get('plan_id') === PLAN_ID)).toBe(true));
    expect(router.state.location.search).toContain('security_code=SYN001.SH');
    expect(router.state.location.search).toContain(`plan_id=${PLAN_ID}`);
});

it.skipIf(!ReviewsPage || !ReviewDetailPage || !detailRoute)('创建表单校验并在成功后进入详情（主线尚未提供 ReviewsPage 或 ReviewDetailPage，或尚未登记 reviews/:id，待实现）', async () => {
    let posted: Record<string, unknown> | null = null;
    server.use(http.post(`${API}/reviews`, async ({ request }) => {
      posted = await request.json() as Record<string, unknown>;
      return HttpResponse.json({
        ...review,
        current_version: { ...version2, lessons: String(posted.lessons ?? '') },
      }, { status: 201 });
    }));
    installDetail();
    const router = renderList();
    fireEvent.click(await screen.findByTestId('new-review'));
    const notes = await screen.findByLabelText(/复盘笔记|笔记|备注/);
    fireEvent.change(notes, { target: { value: '提交前的虚构笔记' } });
    fireEvent.click(screen.getByTestId('submit-review'));
    expect(await screen.findByTestId('review-form-error')).toHaveTextContent('计划或证券至少填写一项。');
    expect(notes).toHaveValue('提交前的虚构笔记');
    expect(posted).toBeNull();

    fireEvent.change(screen.getByLabelText('证券代码'), { target: { value: 'SYN001.SH' } });
    fireEvent.change(screen.getByLabelText('起始日期'), { target: { value: '2026-11-20' } });
    fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2026-11-01' } });
    fireEvent.click(screen.getByTestId('submit-review'));
    expect(await screen.findByTestId('review-form-error')).toHaveTextContent('起止日期必须有序。');
    expect(posted).toBeNull();
    expect(notes).toHaveValue('提交前的虚构笔记');

    fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2026-11-30' } });
    fireEvent.click(screen.getByTestId('submit-review'));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).not.toHaveProperty('metrics');
    expect(posted).not.toHaveProperty('outcome_metrics');
    expect(posted).not.toHaveProperty('return_pct');
    expect((posted as Record<string, unknown> | null)?.lessons).toBe('提交前的虚构笔记');
    await waitFor(() => expect(router.state.location.pathname).toBe(`/reviews/${REVIEW_ID}`));
    expect(await screen.findByTestId('review-detail')).toBeInTheDocument();
});

it.skipIf(!ReviewsPage)('GET 失败显示错误且页面不白屏（主线尚未提供 ReviewsPage，待实现）', async () => {
    server.use(http.get(`${API}/reviews`, () => HttpResponse.json(
      { error: { code: 'INTERNAL_ERROR', message: '虚构读取失败' } },
      { status: 500 },
    )));
    renderList();
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveAttribute('data-code', 'INTERNAL_ERROR');
    expect(alert).toHaveTextContent('加载失败：服务内部错误，请稍后重试');
    expect(alert).toHaveTextContent('INTERNAL_ERROR');
});

it.skipIf(!ReviewsPage)('保存失败显示错误并保留已填笔记（主线尚未提供 ReviewsPage，待实现）', async () => {
    server.use(http.post(`${API}/reviews`, () => HttpResponse.json(
      { error: { code: 'INTERNAL_ERROR', message: '虚构保存失败' } },
      { status: 500 },
    )));
    renderList();
    fireEvent.click(await screen.findByTestId('new-review'));
    fireEvent.change(screen.getByLabelText('证券代码'), { target: { value: 'SYN001.SH' } });
    fireEvent.change(screen.getByLabelText('起始日期'), { target: { value: '2026-11-01' } });
    fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2026-11-20' } });
    const notes = screen.getByLabelText(/复盘笔记|笔记|备注/);
    fireEvent.change(notes, { target: { value: '失败后仍应保留的虚构笔记' } });
    fireEvent.click(screen.getByTestId('submit-review'));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveAttribute('data-code', 'INTERNAL_ERROR');
    expect(alert).toHaveTextContent('保存复盘失败：服务内部错误，请稍后重试');
    expect(alert).toHaveTextContent('INTERNAL_ERROR');
    expect(notes).toHaveValue('失败后仍应保留的虚构笔记');
});
it('/reviews/:id 路由登记与占位状态可观察', async () => {
  installDetail();
  const router = renderDetail();
  await waitFor(() => expect(router.state.initialized).toBe(true));
  if (detailRoute && ReviewDetailPage) {
    expect(await screen.findByTestId('review-detail')).toBeInTheDocument();
    expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();
  } else {
    expect(detailRoute).toBeUndefined();
    expect(screen.queryByTestId('review-detail')).not.toBeInTheDocument();
  }
});

it.skipIf(!detailRoute || !ReviewDetailPage)('/reviews/:id 必须使用 ReviewDetailPage 而非占位（主线尚未登记 reviews/:id 或尚未提供 ReviewDetailPage，待实现）', async () => {
  installDetail();
  const router = renderDetail();
  await waitFor(() => expect(router.state.initialized).toBe(true));
  expect(await screen.findByTestId('review-detail')).toBeInTheDocument();
  expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();
});

it.skipIf(!ReviewDetailPage || !detailRoute)('详情显示笔记和空指标（主线尚未提供 ReviewDetailPage 或尚未登记 reviews/:id，待实现）', async () => {
  installDetail();
  renderDetail();
  expect(await screen.findByTestId('review-notes')).toHaveTextContent('虚构复盘笔记');
  expect(screen.getByTestId('metric-holding_return')).toHaveTextContent('—');
  expect(screen.getByTestId('metric-max_drawdown')).toHaveTextContent('—');
  expect(screen.getByTestId('metric-holding_return').textContent).not.toMatch(/\d/);
});

it.skipIf(!ReviewDetailPage || !detailRoute)('切换版本不覆盖旧笔记（主线尚未提供 ReviewDetailPage 或尚未登记 reviews/:id，待实现）', async () => {
  installDetail(review, [version1, version2]);
  renderDetail();
  expect(await screen.findByTestId('review-notes')).toHaveTextContent('虚构复盘笔记');
  fireEvent.click(await screen.findByTestId('review-version-1'));
  expect(screen.getByTestId('review-notes')).toHaveTextContent('旧版虚构笔记');
});

it.skipIf(!ReviewDetailPage || !detailRoute)('未知状态与时间线类型显示未知（主线尚未提供 ReviewDetailPage 或尚未登记 reviews/:id，待实现）', async () => {
  const unknownReview = {
    ...review,
    data_status: '__proto__',
    gaps: metricGaps,
    current_version: { ...version2, data_status: '__proto__', gaps: metricGaps },
    timeline: [{
      kind: '__proto__',
      at: '2026-11-20T09:00:00+08:00',
      resource_id: null,
      version_no: null,
      evidence_ids: [],
    }],
  };
  installDetail(unknownReview, [version1, version2]);
  renderDetail();
  expect(await screen.findByTestId('review-notes')).toBeInTheDocument();
  const detail = screen.getByTestId('review-detail');
  expect(within(detail).getAllByText('未知', { exact: true }).length).toBeGreaterThanOrEqual(2);
  expect(detail).not.toHaveTextContent('fresh');
  expect(detail).not.toHaveTextContent('无缺口');
});
