/** T-T109 / T-F69：复盘页离线契约测试。页面文件不存在时跳过，存在则严格执行，导入失败必须暴露。 */
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
const pageLoader = Object.values(pageLoaders)[0];
const detailLoader = Object.values(detailLoaders)[0];
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

const emptyMetric = { value: null, n: 0, window: 'synthetic', small_sample: true };
const metrics = {
  holding_return: emptyMetric,
  benchmark_return: emptyMetric,
  excess_return: emptyMetric,
  max_drawdown: emptyMetric,
};

function versionOf(versionNo: number, lessons: string, status = 'partial') {
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
    data_status: status,
    data_as_of: null,
    gaps: [{ key: 'no_source', reason: 'no_source', message: '虚构来源暂缺' }],
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
  gaps: version2.gaps,
  current_version: version2,
  versions: [version1, version2],
  timeline: [
    { kind: 'created', at: '2026-11-10T09:00:00+08:00', resource_id: null, version_no: 1, evidence_ids: [] as string[] },
    { kind: 'version_created', at: '2026-11-20T09:00:00+08:00', resource_id: null, version_no: 2, evidence_ids: [] as string[] },
  ],
};

function installList(items: unknown[] = [review]) {
  server.use(http.get(`${API}/reviews`, () => HttpResponse.json({ items, next_cursor: null })));
}

function installDetail(body: unknown = review, versions: unknown[] = review.versions) {
  server.use(
    http.get(`${API}/reviews/${REVIEW_ID}`, () => HttpResponse.json(body)),
    http.get(`${API}/reviews/${REVIEW_ID}/versions`, () => HttpResponse.json({ items: versions, next_cursor: null })),
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

const listSuite = ReviewsPage ? describe : describe.skip;
listSuite('T-F69 复盘列表与创建', () => {
  it('/reviews 路由使用复盘页面而非占位页', async () => {
    const route = routes.find((item) => item.path === '/')?.children?.find((item) => item.path === 'reviews');
    expect(route).toBeDefined();
    const router = renderList();
    await waitFor(() => expect(router.state.initialized).toBe(true));
    expect(await screen.findByRole('status', { name: /暂无复盘|没有.*复盘/ })).toBeInTheDocument();
    expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();
  });

  it('空列表显示空态', async () => {
    installList([]);
    renderList();
    expect(await screen.findByRole('status', { name: /暂无复盘|没有.*复盘/ })).toBeInTheDocument();
  });

  it('有数据能显示证券与计划，筛选参数随 GET 和 URL 保留', async () => {
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

  it('创建表单拒绝缺少计划和证券及无序日期，合法提交不带计算指标并进入详情', async () => {
    let posted: Record<string, unknown> | null = null;
    server.use(http.post(`${API}/reviews`, async ({ request }) => {
      posted = await request.json() as Record<string, unknown>;
      return HttpResponse.json({
        ...review,
        current_version: { ...version2, lessons: String(posted.lessons ?? '') },
        versions: [version1, { ...version2, lessons: String(posted.lessons ?? '') }],
      }, { status: 201 });
    }));
    installDetail();
    const router = renderList();
    fireEvent.click(await screen.findByTestId('new-review'));
    const notes = await screen.findByLabelText(/复盘笔记|笔记|备注/);
    fireEvent.change(notes, { target: { value: '提交前的虚构笔记' } });
    fireEvent.click(screen.getByTestId('submit-review'));
    expect(await screen.findByTestId('review-form-error')).toHaveTextContent(/至少填写一项/);
    expect(notes).toHaveValue('提交前的虚构笔记');
    expect(posted).toBeNull();

    fireEvent.change(screen.getByLabelText('证券代码'), { target: { value: 'SYN001.SH' } });
    fireEvent.change(screen.getByLabelText('起始日期'), { target: { value: '2026-11-20' } });
    fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2026-11-01' } });
    fireEvent.click(screen.getByTestId('submit-review'));
    expect(await screen.findByTestId('review-form-error')).toHaveTextContent(/日期必须有序|必须有序/);
    expect(posted).toBeNull();
    expect(notes).toHaveValue('提交前的虚构笔记');

    fireEvent.change(screen.getByLabelText('结束日期'), { target: { value: '2026-11-30' } });
    fireEvent.click(screen.getByTestId('submit-review'));
    await waitFor(() => expect(posted).not.toBeNull());
    expect(posted).not.toHaveProperty('metrics');
    expect(posted).not.toHaveProperty('outcome_metrics');
    expect(posted).not.toHaveProperty('return_pct');
    expect(posted?.lessons).toBe('提交前的虚构笔记');
    await waitFor(() => expect(
      router.state.location.pathname === `/reviews/${REVIEW_ID}`
      || (document.body.textContent ?? '').includes('提交前的虚构笔记'),
    ).toBe(true));
  });

  it('GET 失败显示错误且页面不白屏', async () => {
    server.use(http.get(`${API}/reviews`, () => HttpResponse.json(
      { error: { code: 'INTERNAL_ERROR', message: '虚构读取失败' } },
      { status: 500 },
    )));
    renderList();
    expect(await screen.findByRole('alert')).toHaveTextContent(/失败|INTERNAL_ERROR|错误/);
  });

  it('保存失败显示错误并保留已填笔记', async () => {
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
    expect(await screen.findByRole('alert')).toHaveTextContent(/失败|INTERNAL_ERROR|错误/);
    expect(notes).toHaveValue('失败后仍应保留的虚构笔记');
  });
});

const detailSuite = ReviewDetailPage ? describe : describe.skip;
detailSuite('T-F69 复盘详情与版本', () => {
  it('/reviews/:id 路由使用详情页而非占位页', async () => {
    installDetail();
    const route = routes.find((item) => item.path === '/')?.children?.find((item) => item.path === 'reviews/:id');
    expect(route).toBeDefined();
    const router = renderDetail();
    await waitFor(() => expect(router.state.initialized).toBe(true));
    expect(await screen.findByTestId('review-detail')).toBeInTheDocument();
    expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();
  });

  it('显示笔记、来源缺口和空指标，不伪造数字', async () => {
    installDetail();
    renderDetail();
    expect(await screen.findByTestId('review-notes')).toHaveTextContent('虚构复盘笔记');
    expect(screen.getByTestId('review-metric-gap')).toHaveTextContent(/虚构来源暂缺/);
    expect(screen.getByTestId('metric-holding_return')).toHaveTextContent('—');
    expect(screen.getByTestId('metric-max_drawdown')).toHaveTextContent('—');
    expect(screen.getByTestId('metric-holding_return').textContent).not.toMatch(/\d/);
  });

  it('未知 timeline kind 和 data_status 安全展示为未知，切换版本不覆盖旧笔记', async () => {
    const odd = versionOf(2, '虚构复盘笔记', '__proto__');
    odd.gaps = [{ key: 'x', reason: 'constructor', message: '未知状态示例' }];
    const old = versionOf(1, '旧版虚构笔记', 'constructor');
    const body = {
      ...review,
      data_status: '__proto__',
      gaps: odd.gaps,
      current_version: odd,
      versions: [old, odd],
      timeline: [
        { kind: '__proto__', at: odd.created_at, resource_id: null, version_no: 2, evidence_ids: [] as string[] },
        { kind: 'constructor', at: odd.created_at, resource_id: null, version_no: null, evidence_ids: [] as string[] },
      ],
    };
    installDetail(body, [old, odd]);
    renderDetail();
    await screen.findByText('虚构复盘笔记');
    const page = screen.getByTestId('review-detail');
    expect(within(page).getAllByText('未知').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByTestId('review-version-1'));
    expect(screen.getByTestId('review-notes')).toHaveTextContent('旧版虚构笔记');
  });
});
