import { cleanup, render, screen, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { preloadRoutes } from '../../test/preloadRoutes';
import { server } from '../../mocks/server';
import { formatReviewGapClauses, metricLabel, metricValueText } from '../../lib/reviewMetrics';

const API = '/api/v1';
const renderAt = (path: string) => {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
};

const metricKeys = ['holding_return', 'benchmark_return', 'excess_return', 'max_drawdown'] as const;
const emptyStat = () => ({ value: null, n: 0, window: '2026-11-01/2026-11-20', small_sample: true });
const outcomeGaps = () => metricKeys.map((key) => ({ key: `outcome_metrics.${key}`, reason: 'no_source', message: '缺少指标来源' }));
const assertEmptyMetrics = (metrics: Record<string, unknown>) => {
  for (const key of metricKeys) {
    expect(metrics[key]).toEqual(expect.objectContaining({ value: null, n: 0, small_sample: true }));
  }
};

beforeAll(() => preloadRoutes(routes), 30_000);

describe('T-F81 复盘指标口径', () => {
  it('列表与详情标注 000300.SH 未验证，默认指标为空且有缺口', async () => {
    renderAt('/reviews');
    expect(await screen.findByTestId('review-benchmark')).toHaveTextContent('000300.SH');
    expect(screen.getByTestId('review-benchmark')).toHaveTextContent('未验证');
    cleanup();
    renderAt('/reviews/review-example-1');
    expect(await screen.findByTestId('review-metrics')).toHaveTextContent('000300.SH');
    expect(screen.getByTestId('review-metrics')).toHaveTextContent('实际成交复盘结果指标');
    expect(screen.getByTestId('review-benchmark')).toHaveTextContent('未验证');
    for (const key of metricKeys) expect(screen.getByTestId(`metric-${key}`)).toHaveTextContent('—');
    for (const testId of ['review-gap', 'review-metric-gap']) {
      const note = screen.getByTestId(testId);
      const text = note.textContent ?? '';
      expect((text.match(/部分数据缺失/g) ?? [])).toHaveLength(1);
      expect((text.match(/无数据源/g) ?? [])).toHaveLength(1);
      expect((text.match(/待用户录入/g) ?? [])).toHaveLength(1);
      expect(text).toContain('持有收益');
      expect(text).toContain('基准收益');
      expect(text).toContain('超额收益');
      expect(text).toContain('最大回撤');
      expect((text.match(/缺少价格、基准或公式来源，指标暂不计算/g) ?? [])).toHaveLength(1);
      expect((text.match(/缺少可关联成交记录/g) ?? [])).toHaveLength(1);
      expect(text).not.toMatch(/无数据源.*无数据源/);
    }
  });

  it('默认 review-example-2 按指标来源缺口标记为部分缺失', async () => {
    const response = await fetch(`${API}/reviews/review-example-2`);
    const body = await response.json() as {
      data_status: string;
      gaps: { key: string; reason: string }[];
      current_version: {
        data_status: string;
        gaps: { key: string; reason: string }[];
      };
    };
    expect(response.ok).toBe(true);
    expect(body.data_status).toBe('partial');
    expect(body.data_status).not.toBe('pending');
    expect(body.data_status).toBe(body.current_version.data_status);
    expect(body.gaps).toEqual(body.current_version.gaps);
    expect(body.gaps).toHaveLength(metricKeys.length);
    expect(body.gaps.map((gap) => gap.key)).toEqual(metricKeys.map((key) => `outcome_metrics.${key}`));
    expect(body.gaps.every((gap) => gap.reason === 'no_source')).toBe(true);
    expect(body.gaps.some((gap) => gap.reason === 'not_yet_published')).toBe(false);
    assertEmptyMetrics((body.current_version as unknown as { outcome_metrics: Record<string, unknown> }).outcome_metrics);

    renderAt('/reviews/review-example-2');
    await screen.findByTestId('metric-holding_return');
    const page = screen.getByTestId('review-detail');
    expect(within(page).getByTestId('review-gap')).toHaveTextContent('无数据源');
    expect(within(page).getByTestId('review-metric-gap')).toHaveTextContent('无数据源');
    expect(page).not.toHaveTextContent('尚未发布');
    expect(page).not.toHaveTextContent('拉取中');
    for (const key of metricKeys) expect(within(page).getByTestId(`metric-${key}`)).toHaveTextContent('—');
  });

  it('列表与版本响应保留状态块，并逐项标注 null、n=0 和 no_source', async () => {
    const listResponse = await fetch(`${API}/reviews`);
    const list = await listResponse.json() as {
      items: Array<{ current_version_no: number | null; data_status: string; data_as_of: string | null; gaps: { key: string; reason: string }[] }>;
    };
    expect(listResponse.ok).toBe(true);
    const versioned = list.items.filter((item) => item.current_version_no !== null);
    expect(versioned.length).toBeGreaterThan(0);
    for (const item of versioned) {
      expect(item.data_status).toBe('partial');
      expect(item.data_as_of).toBeNull();
      expect(item.gaps.map((gap) => gap.key)).toEqual(expect.arrayContaining(metricKeys.map((key) => `outcome_metrics.${key}`)));
      expect(item.gaps.every((gap) => gap.reason === 'no_source' || gap.key === 'trade_ids')).toBe(true);
    }

    const versionsResponse = await fetch(`${API}/reviews/review-example-1/versions`);
    const versions = await versionsResponse.json() as { items: Array<{ data_status: string; data_as_of: string | null; gaps: { key: string; reason: string }[]; outcome_metrics: Record<string, unknown> }> };
    expect(versionsResponse.ok).toBe(true);
    expect(versions.items).toHaveLength(1);
    const version = versions.items[0];
    expect(version.data_status).toBe('partial');
    expect(version.data_as_of).toBeNull();
    expect(version.gaps.map((gap) => gap.key)).toEqual(expect.arrayContaining(metricKeys.map((key) => `outcome_metrics.${key}`)));
    assertEmptyMetrics(version.outcome_metrics);
  });

  it('按原因合并缺口，去重消息并列出合法指标名', () => {
    const gaps = [
      { key: 'trade_ids', reason: 'user_input_missing', message: '缺少可关联成交记录' },
      { key: 'outcome_metrics.holding_return', reason: 'no_source', message: '缺少价格、基准或公式来源，指标暂不计算' },
      { key: 'outcome_metrics.benchmark_return', reason: 'no_source', message: '缺少价格、基准或公式来源，指标暂不计算' },
      { key: 'outcome_metrics.excess_return', reason: 'no_source', message: '缺少价格、基准或公式来源，指标暂不计算' },
      { key: 'outcome_metrics.max_drawdown', reason: 'no_source', message: '缺少价格、基准或公式来源，指标暂不计算' },
      { key: 'outcome_metrics.max_drawdown', reason: 'no_source', message: '缺少价格、基准或公式来源，指标暂不计算' },
    ] as Parameters<typeof formatReviewGapClauses>[0];
    expect(formatReviewGapClauses(gaps)).toEqual([
      '待用户录入（缺少可关联成交记录）',
      '无数据源（持有收益、基准收益、超额收益、最大回撤：缺少价格、基准或公式来源，指标暂不计算）',
    ]);
  });

  it('未知原因和指标键不发明白名单标签', () => {
    const gaps = [
      { key: 'outcome_metrics.__proto__', reason: 'no_source', message: '缺少来源' },
      { key: 'constructor', reason: 'no_source', message: '缺少来源' },
      { key: 'unknown_metric', reason: 'no_source', message: '其他来源' },
      { key: 'outcome_metrics.unknown_metric', reason: 'constructor', message: '未知来源' },
      { key: 'other', reason: 'totally_unknown', message: '陌生原因' },
    ] as Parameters<typeof formatReviewGapClauses>[0];
    expect(formatReviewGapClauses(gaps)).toEqual([
      '无数据源（缺少来源；其他来源）',
      '未知（未知来源）',
      '未知（陌生原因）',
    ]);
    expect(formatReviewGapClauses(gaps).join('')).not.toMatch(/持有收益|基准收益|超额收益|最大回撤/);
  });

  it('指标白名单拒绝原型键和未知键，缺失值不渲染伪数字', () => {
    expect(metricLabel('__proto__')).toBeUndefined();
    expect(metricLabel('constructor')).toBeUndefined();
    expect(metricLabel('unknown_metric')).toBeUndefined();
    expect(metricValueText({ value: null })).toBe('—');
    expect(metricValueText({ value: 0 })).toBe('0');
    expect(metricValueText({ value: '' })).toBe('—');
    expect(metricValueText({ value: Number.NaN })).toBe('—');
  });

  it('收到污染的 outcome_metrics 时仍只显示四项空指标和对应缺口', async () => {
    const outcomeMetrics = JSON.parse(JSON.stringify({
      holding_return: emptyStat(), benchmark_return: emptyStat(), excess_return: emptyStat(), max_drawdown: emptyStat(),
      constructor: { value: 'forbidden-constructor' }, unknown_metric: { value: 'forbidden-unknown' },
    })) as Record<string, unknown>;
    Object.defineProperty(outcomeMetrics, '__proto__', { value: { value: 'forbidden-proto' }, enumerable: true });
    const version = {
      id: 'review-f81-version', version_no: 1, plan_version_ids: [], trade_ids: [], snapshot_id: null,
      lessons: '安全读取指标', tags: [], attribution: { judgement: [], execution: [], market: [] }, outcome_metrics: outcomeMetrics,
      created_at: '2026-11-20T10:00:00+08:00', data_status: 'partial', data_as_of: null, gaps: outcomeGaps(),
    };
    const body = {
      id: 'review-f81', plan_id: null, security_code: '600000.SH', name: '示例银行', period_start: '2026-11-01', period_end: '2026-11-20',
      current_version_no: 1, created_at: version.created_at, data_status: 'partial', data_as_of: null, gaps: version.gaps,
      current_version: version, timeline: [], evidence: [],
    };
    server.use(
      http.get(`${API}/reviews/review-f81`, () => HttpResponse.json(body)),
      http.get(`${API}/reviews/review-f81/versions`, () => HttpResponse.json({ items: [version], next_cursor: null })),
    );
    renderAt('/reviews/review-f81');
    await screen.findByTestId('metric-holding_return');
    const page = screen.getByTestId('review-detail');
    const metrics = within(page).getByTestId('review-metrics');
    for (const key of metricKeys) expect(within(metrics).getByTestId(`metric-${key}`)).toHaveTextContent('—');
    expect(within(metrics).queryByTestId('metric-__proto__')).not.toBeInTheDocument();
    expect(within(metrics).queryByTestId('metric-constructor')).not.toBeInTheDocument();
    expect(within(metrics).queryByTestId('metric-unknown_metric')).not.toBeInTheDocument();
    expect(metrics).not.toHaveTextContent(/NaN|null|undefined|forbidden/);
    expect(screen.getByTestId('review-metric-gap')).toHaveTextContent('无数据源');
  });
});
