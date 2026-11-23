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
const metricKeys = ['holding_return', 'benchmark_return', 'excess_return', 'max_drawdown'] as const;
const assertEmptyMetrics = (metrics: Record<string, { value: unknown; n: number; small_sample: boolean }>) => {
  for (const key of metricKeys) expect(metrics[key]).toEqual(expect.objectContaining({ value: null, n: 0, small_sample: true }));
};
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
    expect(screen.getByTestId('metric-benchmark_return')).toHaveTextContent('—');
    expect(screen.getByTestId('metric-excess_return')).toHaveTextContent('—');
    expect(screen.getByTestId('metric-max_drawdown')).toHaveTextContent('—');
    expect(screen.getByTestId('review-metric-gap')).toHaveTextContent('无数据源');
    expect(screen.getByTestId('review-evidence')).toHaveTextContent('暂无证据');

    const body = await fetch(`${API}/reviews/review-example-1`).then((response) => response.json()) as {
      data_status: string;
      data_as_of: string | null;
      gaps: { key: string; reason: string }[];
      current_version: { data_status: string; data_as_of: string | null; gaps: { key: string; reason: string }[]; outcome_metrics: Record<string, { value: unknown; n: number; small_sample: boolean }> };
    };
    expect(body.data_status).toBe(body.current_version.data_status);
    expect(body.data_as_of).toBe(body.current_version.data_as_of);
    expect(body.gaps).toEqual(body.current_version.gaps);
    assertEmptyMetrics(body.current_version.outcome_metrics);
    for (const key of ['holding_return', 'benchmark_return', 'excess_return', 'max_drawdown']) {
      expect(body.gaps).toEqual(expect.arrayContaining([expect.objectContaining({ key: `outcome_metrics.${key}`, reason: 'no_source' })]));
    }
  });

  it('缺少当前版本时列表显示横线，详情显示空态且不能保存新版本', async () => {
    const user = userEvent.setup();
    const router = renderAt('/reviews');
    await screen.findByTestId('review-link-review-example-legacy');
    const legacyLink = screen.getByTestId('review-link-review-example-legacy');
    expect(legacyLink.closest('tr')).toHaveTextContent('不可用');
    expect(screen.getByTestId('reviews-table')).toHaveTextContent('—');
    const list = await fetch(`${API}/reviews`).then((response) => response.json()) as {
      items: Array<{ id: string; data_status: string; data_as_of: string | null; current_version_no: number | null; gaps: { key: string; reason: string }[] }>;
    };
    const legacySummary = list.items.find((item) => item.id === 'review-example-legacy');
    expect(legacySummary).toEqual(expect.objectContaining({ data_status: 'unavailable', data_as_of: null, current_version_no: null }));
    expect(legacySummary?.gaps).toEqual([expect.objectContaining({ key: 'outcome_metrics', reason: 'no_source' })]);
    await user.click(screen.getByTestId('review-link-review-example-legacy'));
    await waitFor(() => expect(router.state.location.pathname).toBe('/reviews/review-example-legacy'));
    expect(await screen.findByText('暂无版本内容。')).toBeInTheDocument();
    expect(screen.getByTestId('review-gap')).toHaveTextContent('无数据源');
    expect(screen.getByTestId('review-save-version')).toBeDisabled();

    const body = await fetch(`${API}/reviews/review-example-legacy`).then((response) => response.json()) as {
      data_status: string;
      data_as_of: string | null;
      gaps: { key: string; reason: string }[];
      current_version: unknown;
    };
    expect(body.current_version).toBeNull();
    expect(body.data_status).toBe('unavailable');
    expect(body.data_as_of).toBeNull();
    expect(body.gaps).toEqual([expect.objectContaining({ key: 'outcome_metrics', reason: 'no_source' })]);
    expect(body.gaps.some((gap) => gap.key.startsWith('outcome_metrics.'))).toBe(false);
  });

  it('版本读取保留四项空指标和对应 no_source 缺口', async () => {
    const response = await fetch(`${API}/reviews/review-example-1/versions/1`);
    const version = await response.json() as {
      data_status: string;
      data_as_of: string | null;
      gaps: { key: string; reason: string }[];
      outcome_metrics: Record<string, { value: unknown; n: number; small_sample: boolean }>;
    };
    expect(response.ok).toBe(true);
    expect(version.data_status).toBe('partial');
    expect(version.data_as_of).toBeNull();
    assertEmptyMetrics(version.outcome_metrics);
    expect(version.gaps).toEqual(expect.arrayContaining(metricKeys.map((key) => expect.objectContaining({ key: `outcome_metrics.${key}`, reason: 'no_source' }))));
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
    const router = renderAt('/reviews');
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
    const createdId = router.state.location.pathname.split('/').pop();
    const created = await fetch(`${API}/reviews/${createdId}`).then((response) => response.json()) as { current_version: { outcome_metrics: { holding_return: { window: string } } } };
    expect(created.current_version.outcome_metrics.holding_return.window).toBe('2026-11-20/2026-11-30');
  });

  it('版本切换及未知 timeline kind、状态安全显示为未知', async () => {
    const user = userEvent.setup();
    const version = (no: number, lessons: string) => ({
      id: `v-${no}`, version_no: no, plan_version_ids: [], trade_ids: [], snapshot_id: null,
      lessons, tags: [], attribution: { judgement: [], execution: [], market: [] },
      outcome_metrics: { holding_return: { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true }, benchmark_return: { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true }, excess_return: { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true }, max_drawdown: { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true } },
      created_at: '2026-11-20T10:00:00+08:00', data_status: '__proto__', data_as_of: null, gaps: [{ key: 'x', reason: 'constructor', message: '未知状态示例' }],
    });
    const v1 = version(1, '旧版本笔记');
    const v2 = version(2, '当前版本笔记');
    const body = { id: 'review-unknown', plan_id: null, security_code: '600000.SH', name: '示例银行', period_start: '2026-11-01', period_end: '2026-11-20', current_version_no: 2, created_at: v2.created_at, data_status: '__proto__', data_as_of: null, gaps: v2.gaps, current_version: v2, timeline: [{ kind: 'review_version', at: v2.created_at, resource_id: null, version_no: 2, evidence_ids: [] }, { kind: 'plan_version', at: v2.created_at, resource_id: null, version_no: null, evidence_ids: [] }, { kind: 'trade', at: v2.created_at, resource_id: null, version_no: null, evidence_ids: [] }, { kind: '__proto__', at: v2.created_at, resource_id: null, version_no: null, evidence_ids: [] }, { kind: 'constructor', at: v2.created_at, resource_id: null, version_no: null, evidence_ids: [] }, { kind: 'created', at: v2.created_at, resource_id: null, version_no: null, evidence_ids: [] }] };
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
    const timeline = within(page).getByTestId('review-timeline');
    expect(timeline).toHaveTextContent('复盘版本');
    expect(timeline).toHaveTextContent('计划版本');
    expect(timeline).toHaveTextContent('成交');
    const unknownKinds = within(timeline).getAllByText('未知');
    expect(unknownKinds).toHaveLength(3);
    expect(unknownKinds.every((el) => el.classList.contains('muted'))).toBe(true);
  });

  it('详情证据缺失或为空时显示空态，时间线证据按本详情解析', async () => {
    const evidence = { id: 'EV-1', key: 'close', value: '10.00', unit: '元', provider: 'system', endpoint: null, data_as_of: '2026-11-20T15:00:00+08:00', fetched_at: '2026-11-20T15:01:00+08:00', epistemic_type: 'fact' };
    const version = { id: 'evidence-version', version_no: 1, plan_version_ids: [], trade_ids: [], snapshot_id: null, lessons: '带证据的复盘', tags: [], attribution: { judgement: [], execution: [], market: [] }, outcome_metrics: { holding_return: { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true }, benchmark_return: { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true }, excess_return: { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true }, max_drawdown: { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true } }, created_at: '2026-11-20T10:00:00+08:00', data_status: 'partial', data_as_of: null, gaps: [{ key: 'outcome_metrics.holding_return', reason: 'no_source', message: '缺少来源' }, { key: 'outcome_metrics.benchmark_return', reason: 'no_source', message: '缺少来源' }, { key: 'outcome_metrics.excess_return', reason: 'no_source', message: '缺少来源' }, { key: 'outcome_metrics.max_drawdown', reason: 'no_source', message: '缺少来源' }] };
    const body = { id: 'review-evidence', plan_id: null, security_code: '600000.SH', name: '示例银行', period_start: '2026-11-01', period_end: '2026-11-20', current_version_no: 1, created_at: version.created_at, data_status: 'partial', data_as_of: null, gaps: version.gaps, current_version: version, evidence: [evidence], timeline: [{ kind: 'review_version', at: version.created_at, resource_id: null, version_no: 1, evidence_ids: ['EV-1', 'MISSING'] }] };
    server.use(
      http.get(`${API}/reviews/review-evidence`, () => HttpResponse.json(body)),
      http.get(`${API}/reviews/review-evidence/versions`, () => HttpResponse.json({ items: [version], next_cursor: null })),
    );
    renderAt('/reviews/review-evidence');
    await screen.findByText('带证据的复盘');
    expect(screen.getByTestId('review-evidence')).toHaveTextContent('close = 10.00元');
    expect(screen.getByTestId('review-timeline')).toHaveTextContent('MISSING?');
  });

  it('保存新版本在版本冲突时提示当前版本号', async () => {
    const user = userEvent.setup();
    server.use(http.post(`${API}/reviews/review-example-1/versions`, () => HttpResponse.json({ error: { code: 'VERSION_CONFLICT', message: '版本号已变化', details: { current_version_no: 3 }, request_id: 'mock-conflict' } }, { status: 409 })));
    renderAt('/reviews/review-example-1');
    await screen.findByText(/先记录执行条件/);
    await user.click(screen.getByTestId('review-save-version'));
    expect(await screen.findByTestId('review-version-save-error')).toHaveTextContent('第 3 版');
  });
});
