import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { preloadRoutes } from '../../test/preloadRoutes';
import { server } from '../../mocks/server';

const API = '/api/v1';
const outcomeMetricKeys = ['holding_return', 'benchmark_return', 'excess_return', 'max_drawdown'] as const;
const outcomeMetricGaps = () => outcomeMetricKeys.map((key) => ({ key: `outcome_metrics.${key}`, reason: 'no_source', message: '缺少价格、基准或公式来源，指标暂不计算' }));
const renderAt = (path: string) => {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
};
const metrics = () => Object.fromEntries(['holding_return', 'benchmark_return', 'excess_return', 'max_drawdown'].map((key) => [key, { value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true }]));
const version = (no: number, lessons: string, planVersionIds: string[] = [], tradeIds: string[] = [], extra: Record<string, unknown> = {}) => ({
  id: `review-f72-v${no}`, version_no: no, plan_version_ids: planVersionIds, trade_ids: tradeIds, snapshot_id: null,
  lessons, tags: [], attribution: { judgement: [], execution: [], market: [] }, outcome_metrics: metrics(), created_at: `2026-11-${no}T10:00:00+08:00`,
  data_status: 'partial', data_as_of: null, gaps: outcomeMetricGaps(), ...extra,
});

beforeAll(() => preloadRoutes(routes), 30_000);

describe('T-F72 复盘补充覆盖', () => {
  it('列表空态不是错误', async () => {
    server.use(http.get(`${API}/reviews`, () => HttpResponse.json({ items: [], next_cursor: null })));
    renderAt('/reviews');
    expect(await screen.findByText('暂无复盘记录')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('深链版本保留冻结计划与成交引用', async () => {
    const user = userEvent.setup();
    const v1 = version(1, 'v1 冻结笔记', ['plan-version-f72-v1'], ['trade-f72-1']);
    const v2 = version(2, 'v2 当前笔记', ['plan-version-f72-v2'], ['trade-f72-2']);
    const body = {
      id: 'review-f72', plan_id: 'plan-example-1', security_code: '600000.SH', name: '示例银行', period_start: '2026-11-01', period_end: '2026-11-20',
      current_version_no: 2, created_at: v2.created_at, data_status: v2.data_status, data_as_of: v2.data_as_of, gaps: v2.gaps, current_version: v2,
      timeline: [{ kind: 'review_version', at: v2.created_at, resource_id: 'review-f72', version_no: 1, evidence_ids: [] }],
    };
    for (const current of [v1, v2]) {
      expect(current.data_status).toBe('partial');
      expect(current.gaps).toEqual(expect.arrayContaining(outcomeMetricGaps()));
    }
    expect(body.data_status).toBe('partial');
    expect(body.gaps).toEqual(expect.arrayContaining(outcomeMetricGaps()));
    expect(body.data_status).toBe(body.current_version.data_status);
    expect(body.gaps).toEqual(body.current_version.gaps);
    server.use(
      http.get(`${API}/reviews/review-f72`, () => HttpResponse.json(body)),
      http.get(`${API}/reviews/review-f72/versions`, () => HttpResponse.json({ items: [v1, v2], next_cursor: null })),
    );
    const router = renderAt('/reviews/review-f72?keep=1&version=1');
    await screen.findByText('v1 冻结笔记');
    expect(screen.getByTestId('review-plan-link')).toHaveAttribute('href', '/plans/plan-example-1?plan_version_id=plan-version-f72-v1');
    expect(screen.getByTestId('review-trade-link-trade-f72-1')).toHaveAttribute('href', '/portfolio?tab=trades&trade_id=trade-f72-1');
    await user.click(screen.getByTestId('review-version-2'));
    await waitFor(() => expect(router.state.location.search).toBe('?keep=1&version=2'));
    expect(screen.getByTestId('review-notes')).toHaveTextContent('v2 当前笔记');
    await router.navigate('/reviews/review-f72?version=2');
    expect(await screen.findByText('v2 当前笔记')).toBeInTheDocument();
  });

  it('空指标、缺口和未知枚举安全显示', async () => {
    const v = version(1, '缺数笔记', [], [], {
      data_status: '__proto__',
      gaps: [
        { key: 'a', reason: 'no_source', message: '没有来源' },
        { key: 'b', reason: 'user_input_missing', message: '等待手写' },
        { key: 'c', reason: 'not_yet_published', message: '尚未发布' },
        { key: 'd', reason: 'constructor', message: '未知原因' },
        { key: 'e', reason: 'totally_unknown', message: '陌生原因' },
      ],
    });
    const body = {
      id: 'review-f72-unknown', plan_id: null, security_code: '600000.SH', name: '示例银行', period_start: '2026-11-01', period_end: '2026-11-20',
      current_version_no: 1, created_at: v.created_at, data_status: '__proto__', data_as_of: null, gaps: v.gaps, current_version: v,
      // __proto__, constructor, and totally_unknown are intentional abnormal enum inputs for the fallback test.
      timeline: [{ kind: '__proto__', at: v.created_at, resource_id: null, version_no: 1, evidence_ids: [] }, { kind: 'constructor', at: v.created_at, resource_id: null, version_no: null, evidence_ids: [] }],
    };
    server.use(
      http.get(`${API}/reviews/review-f72-unknown`, () => HttpResponse.json(body)),
      http.get(`${API}/reviews/review-f72-unknown/versions`, () => HttpResponse.json({ items: [v], next_cursor: null })),
    );
    renderAt('/reviews/review-f72-unknown');
    const metric = await screen.findByTestId('metric-holding_return');
    const page = screen.getByTestId('review-detail');
    expect(metric).toHaveTextContent('—');
    expect(screen.getByTestId('review-metric-gap')).toHaveTextContent('无数据源');
    expect(screen.getByTestId('review-metric-gap')).toHaveTextContent('待用户录入');
    expect(screen.getByTestId('review-metric-gap')).toHaveTextContent('尚未发布');
    expect(page).toHaveTextContent('未知');
  });

  it('保存失败仍保留用户输入', async () => {
    const user = userEvent.setup();
    server.use(http.post(`${API}/reviews`, () => HttpResponse.json({ error: { code: 'VALIDATION_ERROR', message: '保存失败示例', details: null, request_id: 'mock-f72' } }, { status: 400 })));
    renderAt('/reviews');
    await user.click(await screen.findByTestId('new-review'));
    await user.type(screen.getByLabelText('证券代码'), '600000.SH');
    await user.type(screen.getByLabelText('起始日期'), '2026-11-01');
    await user.type(screen.getByLabelText('结束日期'), '2026-11-20');
    await user.type(screen.getByLabelText('复盘笔记'), '缺市场环境也要保留的手写经验');
    await user.type(screen.getByLabelText('标签'), '执行纪律');
    await user.click(screen.getByTestId('submit-review'));
    expect(await screen.findByText(/保存复盘失败/)).toBeInTheDocument();
    expect(screen.getByLabelText('证券代码')).toHaveValue('600000.SH');
    expect(screen.getByLabelText('起始日期')).toHaveValue('2026-11-01');
    expect(screen.getByLabelText('结束日期')).toHaveValue('2026-11-20');
    expect(screen.getByLabelText('复盘笔记')).toHaveValue('缺市场环境也要保留的手写经验');
    expect(screen.getByLabelText('标签')).toHaveValue('执行纪律');
  });
});
