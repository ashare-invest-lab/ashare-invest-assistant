import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { apiGet } from '../api/client';
import type { RiskControlSetting } from '../api/phase2Types';
import { RISK_CONTROL } from '../i18n/labels';
import { DAILY_REPORTS, REPORT_DATE } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { DailyReportPage } from './DailyReportPage';
import { RiskControlsPage } from './RiskControlsPage';
function open(path: string) {
  const router = createMemoryRouter([
    { path: '/daily-reports/:date', element: <DailyReportPage /> },
    { path: '/risk-controls', element: <RiskControlsPage /> },
  ], { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
}
beforeEach(() => mockLoginAs('demo_user'));
it('大量缺口先保留总数与警示，展开后完整读取，不挡后续章节', async () => {
  const report = structuredClone(DAILY_REPORTS[0]);
  report.gaps = Array.from({ length: 40 }, (_, i) => ({ key: `synthetic.${i}`, reason: 'no_source' as const, message: `合成缺口 ${i + 1}` }));
  server.use(http.get('/api/v1/daily-reports/:date', () => HttpResponse.json(report)));
  open(`/daily-reports/${REPORT_DATE}`);
  const page = await screen.findByTestId('daily-report');
  const details = within(page).getByTestId('report-gap-details');
  expect(details).not.toHaveAttribute('open');
  expect(within(page).getByTestId('report-gaps')).toHaveTextContent('数据缺口 40 项');
  expect(details.querySelectorAll('li')).toHaveLength(40);
  expect(within(details).getByText('合成缺口 40')).not.toBeVisible();
  expect(within(page).getByRole('heading', { name: '账户与市场' })).toBeVisible();
  await userEvent.click(within(details).getByText('查看全部 40 项缺口与来源说明'));
  expect(details).toHaveAttribute('open');
  expect(within(details).getByText('合成缺口 40')).toBeVisible();
});
it('无缺口时不增加空的展开入口', async () => {
  server.use(http.get('/api/v1/daily-reports/:date', () => HttpResponse.json({ ...DAILY_REPORTS[0], gaps: [] })));
  open(`/daily-reports/${REPORT_DATE}`);
  const page = await screen.findByTestId('daily-report');
  expect(within(page).queryByTestId('report-gap-details')).toBeNull();
});
it('风控定位入口完整保留服务端启用状态并指向对应设置，不自动保存', async () => {
  const settings = await apiGet<RiskControlSetting[]>('/risk-controls');
  const writes: string[] = [];
  server.events.on('request:start', ({ request }) => { if (request.method !== 'GET') writes.push(request.method); });
  open('/risk-controls');
  const nav = await screen.findByRole('navigation', { name: '风控设置定位' });
  expect(within(nav).getAllByRole('link')).toHaveLength(settings.length);
  for (const item of settings) {
    const link = within(nav).getByRole('link', { name: `${RISK_CONTROL[item.control]} · ${item.enabled ? '已启用' : '已关闭'}` });
    expect(link).toHaveAttribute('href', `#risk-setting-${item.control}`);
    expect(document.getElementById(`risk-setting-${item.control}`)).toBeInTheDocument();
  }
  expect(screen.getByTestId('risk-settings-overview')).toHaveTextContent('编辑后需点击对应保存按钮');
  expect(writes).toEqual([]);
});
