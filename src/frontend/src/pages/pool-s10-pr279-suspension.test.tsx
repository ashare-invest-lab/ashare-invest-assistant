import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { apiGet } from '../api/client';
import { CONTRACT_VERSION, ENUMS } from '../api/enums';
import type { Bar, BarsResponse, Gap, TodayResponse } from '../api/types';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { CONFIRMED_DAILY_SUSPENSION, DAILY_REPORTS, REPORT_DATE, uid } from '../mocks/fixtures';
import { setMockLicence } from '../mocks/licenceStore';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { DailyReportPage } from './DailyReportPage';
import { PriceChartPanel } from './stock/PriceChartPanel';
import { TodayPage } from './today/TodayPage';

vi.mock('../components/charts/KlineChart', () => ({
  KlineChart: ({ bars, empty }: { bars: Bar[]; empty: ReactNode }) => bars.length
    ? <div data-testid="history-bars">{bars.map((bar) => bar.t).join('、')}</div>
    : <div data-testid="empty-bars">{empty}</div>,
}));

const { code, date } = CONFIRMED_DAILY_SUSPENSION;
const barsPath = `/securities/${code}/bars`;
const suspension: Gap = { key: 'synthetic.suspension', reason: 'suspended', message: '示例能源：本交易日确认停牌' };
const missing: Gap = { key: 'pipeline.daily_bars_missing:600000.SH', reason: 'no_source', message: '某示例证券缺少可用日 K' };

function mount(path: string) {
  const router = createMemoryRouter([
    { path: '/charts', element: <PriceChartPanel code={code} /> },
    { path: '/daily-reports/:date', element: <DailyReportPage /> },
    { path: '/today', element: <TodayPage /> },
  ], { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
}

function mockReport(gaps: Gap[]) {
  server.use(http.get('/api/v1/daily-reports/:date', () => HttpResponse.json({ ...DAILY_REPORTS[0], gaps })));
}

beforeEach(() => mockLoginAs('demo_user'));

it('版本和理由枚举对齐 v0.2.11，原七值顺序保留', () => {
  expect(CONTRACT_VERSION).toBe('v0.2.11');
  expect(ENUMS.gap_reason).toEqual([
    'no_source', 'not_yet_published', 'upstream_error', 'quota_deferred', 'user_input_missing',
    'data_licence_unavailable', 'not_applicable', 'suspended',
  ]);
});

it('本人有效模拟证书下，确证停牌单日没有有效 K 也没有伪造时点', async () => {
  const raw = await apiGet<BarsResponse>(barsPath, { freq: 'd', adjust: 'none', from: date, to: date });
  expect(raw).toMatchObject({ freq: 'd', adjust: 'none', items: [], next_before: null, data_as_of: null });
  expect(raw.gaps).toEqual([{ key: `bars.${date}`, reason: 'suspended', message: '当日停牌（示例）' }]);
});

it('含停牌日的原始日线窗口保留历史和游标，下一页不重复停牌说明', async () => {
  const raw = await apiGet<BarsResponse>(barsPath, { freq: 'd', adjust: 'none', limit: 2 });
  expect(raw.items).toHaveLength(2);
  expect(raw.items.every((bar) => bar.t < date)).toBe(true);
  expect(raw.gaps.map((g) => g.reason)).toEqual(['suspended']);
  expect(raw.next_before).toBe(raw.items[0].t);
  const older = await apiGet<BarsResponse>(barsPath, { freq: 'd', adjust: 'none', before: raw.next_before, limit: 2 });
  expect(older.items).toHaveLength(2);
  expect(older.items.every((bar) => bar.t < raw.items[0].t)).toBe(true);
  expect(older.gaps.map((g) => g.reason)).not.toContain('suspended');
});

it('缺行和无源保持 no_source，复权与无有效本人证书不下发确证停牌', async () => {
  const day = { freq: 'd', from: date, to: date } as const;
  const cases = [
    apiGet<BarsResponse>(barsPath, { ...day, adjust: 'qfq' }),
    apiGet<BarsResponse>('/securities/830001.BJ/bars', { ...day, adjust: 'none' }),
    apiGet<BarsResponse>(barsPath, { ...day, adjust: 'none', from: '2030-01-01', to: '2030-01-01' }),
  ];
  for (const raw of await Promise.all(cases)) {
    expect(raw.items).toEqual([]);
    expect(raw.gaps.map((g) => g.reason)).toEqual(['no_source']);
  }
  mockLoginAs('admin');
  const otherOwner = await apiGet<BarsResponse>(barsPath, { ...day, adjust: 'none' });
  expect(otherOwner.gaps.map((g) => g.reason)).toEqual(['no_source']);
  mockLoginAs('demo_user');
  setMockLicence(uid(2), { status: 'expired' });
  const expired = await apiGet<BarsResponse>(barsPath, { ...day, adjust: 'none' });
  expect(expired.gaps.map((g) => g.reason)).toEqual(['data_licence_unavailable']);
});

it.each([false, true])('前复权明确无源时沿既有入口回落并说明停牌（单日：%s）', async (singleDay) => {
  const window = singleDay ? { from: date, to: date } : { limit: 2 };
  const raw = await apiGet<BarsResponse>(barsPath, { freq: 'd', adjust: 'none', ...window });
  server.use(http.get(`/api/v1${barsPath}`, ({ request }) => HttpResponse.json(new URL(request.url).searchParams.get('adjust') === 'qfq'
    ? { ...raw, adjust: 'qfq', items: [], next_before: null, data_status: 'unavailable', data_as_of: null,
      gaps: [{ key: 'bars', reason: 'no_source', message: '示例：前复权暂不可用' }] }
    : raw)));
  mount('/charts');
  if (singleDay) {
    expect(await screen.findByTestId('empty-bars')).toHaveTextContent('无日 K 数据：停牌');
    expect(screen.getByTestId('chart-gap-note')).toHaveTextContent('停牌说明');
  } else {
    const history = await screen.findByTestId('history-bars');
    expect(history).toHaveTextContent(raw.items[0].t);
    expect(history).toHaveTextContent(raw.items[1].t);
    expect(screen.getByTestId('chart-gap-note')).toHaveTextContent('数据已过期');
  }
  expect(screen.getByTestId('chart-gap-note')).toHaveTextContent('当日停牌（示例）');
});

it('日报的故障计数仅含实际缺数，展开保留停牌和缺数两条来源', async () => {
  mockReport([suspension, missing]);
  mount(`/daily-reports/${REPORT_DATE}`);
  const page = await screen.findByTestId('daily-report');
  expect(within(page).getByRole('link', { name: '数据缺口（1）' })).toBeVisible();
  expect(within(page).getByTestId('report-gaps')).toHaveTextContent('数据缺口 1 项');
  const details = within(page).getByTestId('report-gap-details');
  await userEvent.click(within(details).getByText('查看全部 2 项数据与来源说明'));
  expect(within(details).getByText(suspension.message)).toBeVisible();
  expect(within(details).getByText(missing.message)).toBeVisible();
});

it('只有停牌说明的日报仍可定位，却不展示缺数警告', async () => {
  mockReport([suspension]);
  mount(`/daily-reports/${REPORT_DATE}`);
  const page = await screen.findByTestId('daily-report');
  expect(within(page).getByRole('link', { name: '停牌说明' })).toBeVisible();
  expect(within(page).getByTestId('report-gaps')).toHaveTextContent('已确认停牌');
  expect(within(page).getByTestId('report-gaps')).not.toHaveClass('ant-alert-warning');
});

it.each([true, false])('今日页保留日报停牌说明与既有缺数判定（含实际缺数：%s）', async (hasMissing) => {
  const today = await apiGet<TodayResponse>('/today');
  server.use(http.get('/api/v1/today', () => HttpResponse.json({
    ...today, daily_report: { date: REPORT_DATE, status: 'ready' }, data_gaps: { items: [], more: false },
  })));
  mockReport(hasMissing ? [suspension, missing] : [suspension]);
  mount('/today');
  const gapCard = await screen.findByTestId('today-data-gaps');
  const notes = await within(gapCard).findByRole('list', { name: '日报停牌说明' });
  expect(notes).toHaveTextContent(suspension.message);
  if (hasMissing) {
    const gaps = within(gapCard).getByTestId('today-report-gaps');
    expect(within(gaps).getAllByRole('listitem')).toHaveLength(1);
    expect(gaps).toHaveTextContent('今日缺少日 K 数据');
  } else {
    expect(within(gapCard).queryByTestId('today-report-gaps')).toBeNull();
    expect(within(gapCard).getByText('暂无缺数故障')).toBeVisible();
  }
});
