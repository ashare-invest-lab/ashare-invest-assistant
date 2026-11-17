import { render, screen, within } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { ApiError } from '../api/client';
import { ErrorBox } from '../components/common';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { DailyReportIndex, DailyReportPage } from './DailyReportPage';
import { RiskControlsPage } from './RiskControlsPage';
import { SuggestionIndex } from './SuggestionIndex';
function open(path: string) {
  const router = createMemoryRouter([
    { path: '/daily-reports', element: <DailyReportIndex /> },
    { path: '/daily-reports/:date', element: <DailyReportPage /> },
    { path: '/risk-controls', element: <RiskControlsPage /> },
    { path: '/suggestions', element: <SuggestionIndex /> },
  ], { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
}
beforeEach(() => mockLoginAs('demo_user'));
it.each([
  ['/daily-reports', '/api/v1/daily-reports', '暂无日报', '不触发生成'],
  ['/risk-controls?tab=events', '/api/v1/risk-controls/events', '暂无符合条件的风控事件；不是“风险为零”。', '查看已有记录'],
  ['/suggestions', '/api/v1/suggestions', '当前筛选没有候选信号卡', '不代表没有风险或已有模拟结果'],
])('成功空响应%s使用统一状态说明，不转成错误或伪造结果', async (path, endpoint, title, description) => {
  server.use(http.get(endpoint, () => HttpResponse.json({ items: [], next_cursor: null })));
  open(path);
  const empty = await screen.findByRole('status', { name: title });
  expect(empty).toHaveAttribute('data-state', 'empty');
  expect(empty).toHaveTextContent(description);
  expect(document.querySelector('[data-state="error"]')).toBeNull();
});
it('日报真实404类错误保留错误码与返回入口，不吞成暂无日报', async () => {
  server.use(http.get('/api/v1/daily-reports/:date', () => HttpResponse.json({ error: { code: 'NOT_FOUND', message: '合成日报不存在', details: null, request_id: 'synthetic-rf2-request' } }, { status: 404 })));
  open('/daily-reports/1900-01-01');
  const error = await screen.findByRole('alert');
  expect(error).toHaveAttribute('data-state', 'error');
  expect(error).toHaveAttribute('data-code', 'NOT_FOUND');
  expect(error).toHaveTextContent('内容不存在或已删除');
  expect(error).toHaveTextContent('synthetic-rf2-request');
  expect(screen.getByRole('link', { name: '查看最新一期日报 ›' })).toHaveAttribute('href', '/daily-reports');
  expect(document.querySelector('[data-state="empty"]')).toBeNull();
});
it('已停用证券404仍优先提示新代码', () => {
  render(<MemoryRouter><ErrorBox error={new ApiError(404, 'NOT_FOUND', '', { superseded_by: '920001.BJ' }, 'synthetic-rf2', '/api/v1/securities/830001.BJ')} /></MemoryRouter>);
  expect(screen.getByRole('alert')).toHaveAttribute('data-code', 'SUPERSEDED');
  expect(screen.getByRole('alert')).toHaveTextContent('920001.BJ');
  expect(document.querySelector('[data-state="empty"]')).toBeNull();
});
it.each([
  [401, 'AUTH_REQUIRED', null, '去登录 ›', '/login'],
  [409, 'DATA_LICENCE_UNAVAILABLE', null, '去设置数据证书 ›', '/settings/data-licence'],
] as const)('错误%s保留既有处理入口', (status, code, details, label, href) => {
  render(<MemoryRouter><ErrorBox error={new ApiError(status, code, '', details, 'synthetic-rf2')} /></MemoryRouter>);
  const error = screen.getByRole('alert');
  expect(error).toHaveAttribute('data-state', 'error');
  expect(within(error).getByRole('link', { name: label })).toHaveAttribute('href', href);
});
it('首导未完成仍给部署说明，不替换成空集合', () => {
  render(<MemoryRouter><ErrorBox error={new ApiError(500, 'INTERNAL_ERROR', '', { issue: 'security_master_bootstrap_required' }, 'synthetic-rf2')} /></MemoryRouter>);
  expect(screen.getByRole('alert')).toHaveTextContent('证券主数据尚未完成首次导入');
  expect(screen.getByRole('alert')).toHaveAttribute('data-code', 'security_master_bootstrap_required');
  expect(document.querySelector('[data-state="empty"]')).toBeNull();
});
