import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Alert } from '../../api/planAlertTypes';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { uid } from '../../mocks/fixtures';
import { errorBody } from '../../mocks/handlerUtils';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { todayAlerts } from '../../mocks/todayFixtures';
import { AlertsPage } from './AlertsPage';

beforeEach(() => mockLoginAs('demo_user'));

function renderAlerts(search = '') {
  const router = createMemoryRouter([
    { path: '/alerts', element: <AlertsPage /> },
    { path: '/alerts/:id', element: <h1>提醒详情</h1> },
  ], { initialEntries: [`/alerts${search}`] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

async function choose(filter: string, text: string) {
  fireEvent.mouseDown(within(screen.getByTestId(filter)).getByRole('combobox'));
  fireEvent.click(await screen.findByText(text, { selector: '.ant-select-item-option-content' }));
}

describe('T-F51 提醒中心筛选与列表状态', () => {
  it('全部状态包含已忽略，取消勾选恢复默认；状态多选可以移除和清空', async () => {
    const user = userEvent.setup();
    const router = renderAlerts();
    const dismissed = `alert-link-${uid(7105)}`;
    await screen.findByTestId(`alert-link-${uid(7199)}`);
    expect(screen.queryByTestId(dismissed)).not.toBeInTheDocument();
    await user.click(screen.getByRole('checkbox', { name: '全部状态' }));
    expect(await screen.findByTestId(dismissed)).toBeInTheDocument();
    expect(within(screen.getByTestId('alert-filter-status')).getByRole('combobox')).toBeDisabled();
    await user.click(screen.getByRole('checkbox', { name: '全部状态' }));
    await waitFor(() => expect(screen.queryByTestId(dismissed)).not.toBeInTheDocument());
    expect(router.state.location.search).toBe('');
    const statuses = screen.getByTestId('alert-filter-status');
    await user.click(within(statuses).getByRole('combobox'));
    await user.keyboard('{Backspace}');
    expect(new URLSearchParams(router.state.location.search).get('status')).toBe('new');
    await user.click(within(statuses).getByRole('button', { name: 'Clear' }));
    expect(router.state.location.search).toBe('');
  });

  it('来源、级别、证券代码和计划筛选相互保留，并可清除', async () => {
    const router = renderAlerts(`?plan_id=${uid(7302)}`);
    await screen.findByTestId(`alert-link-${uid(7199)}`);
    await choose('alert-filter-origin', '计划条件');
    await choose('alert-filter-severity', '重要');
    const code = screen.getByPlaceholderText('证券代码');
    fireEvent.change(code, { target: { value: ' 002001.sz ' } });
    fireEvent.keyDown(code, { key: 'Enter', code: 'Enter' });
    await waitFor(() => expect(new URLSearchParams(router.state.location.search).get('security_code')).toBe('002001.SZ'));
    expect(new URLSearchParams(router.state.location.search).get('origin')).toBe('plan_condition');
    expect(new URLSearchParams(router.state.location.search).get('severity')).toBe('important');
    expect(await screen.findByTestId(`alert-link-${uid(7199)}`)).toBeInTheDocument();
    fireEvent.click(within(screen.getByTestId('alert-filter-plan')).getByRole('button', { name: '关闭' }));
    expect(new URLSearchParams(router.state.location.search).has('plan_id')).toBe(false);
    await choose('alert-filter-origin', '全部来源');
    await choose('alert-filter-severity', '全部级别');
    expect(new URLSearchParams(router.state.location.search).has('origin')).toBe(false);
    expect(new URLSearchParams(router.state.location.search).has('severity')).toBe(false);
  });

  it('无效筛选回退到默认，搜索无匹配时显示空态', async () => {
    renderAlerts('?status=unknown&origin=unknown&severity=unknown');
    expect(await screen.findByTestId(`alert-link-${uid(7199)}`)).toBeInTheDocument();
    expect(screen.getByTestId('alert-filter-origin')).toHaveTextContent('全部来源');
    expect(screen.getByTestId('alert-filter-severity')).toHaveTextContent('全部级别');
    const code = screen.getByPlaceholderText('证券代码');
    fireEvent.change(code, { target: { value: '999999.SH' } });
    fireEvent.keyDown(code, { key: 'Enter', code: 'Enter' });
    expect(await screen.findByText('没有符合条件的提醒')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('首屏加载失败展示服务错误', async () => {
    server.use(http.get('/api/v1/alerts', () => HttpResponse.json(
      errorBody('INTERNAL_ERROR', '读取失败'), { status: 500 },
    )));
    renderAlerts();
    expect(await screen.findByRole('alert')).toHaveTextContent('服务内部错误，请稍后重试');
  });

  it('账户级提醒显示来源和北京时间；下一页失败保留内容并可重试，点击标题打开详情', async () => {
    const account: Alert = {
      ...todayAlerts()[0], id: uid(9901), title: '账户数据待核对', security_code: null, name: null,
      checklist: [], snapshot_id: null, handled_at: null, evidence: [],
      triggered_at: '2026-11-02T02:31:00Z',
    };
    let failNext = true;
    server.use(http.get('/api/v1/alerts', ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      if (!cursor) return HttpResponse.json({ items: [account], next_cursor: 'page-2' });
      if (failNext) {
        failNext = false;
        return HttpResponse.json(errorBody('INTERNAL_ERROR', '下一页失败'), { status: 500 });
      }
      return HttpResponse.json({ items: [{ ...account, id: uid(9902), title: '第二条提醒' }], next_cursor: null });
    }));
    const router = renderAlerts();
    expect(await screen.findByRole('link', { name: '账户数据待核对' })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '账户级' })).toBeInTheDocument();
    expect(screen.getByText('11-02 10:31')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }));
    expect(await screen.findByText('下一页加载失败，已加载的内容保留')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '账户数据待核对' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }));
    expect(await screen.findByRole('link', { name: '第二条提醒' })).toBeInTheDocument();
    expect(screen.getByText('已显示全部 2 条')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: '账户数据待核对' }));
    expect(await screen.findByRole('heading', { name: '提醒详情' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/alerts/${account.id}`);
  });
});
