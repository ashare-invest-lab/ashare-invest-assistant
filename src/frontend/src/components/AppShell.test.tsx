import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import type { Notification } from '../api/types';
import { ME, NOTIFICATIONS } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { TestRouterProvider } from '../test/TestRouterProvider';
import { AppShell } from './AppShell';

const API = '/api/v1';
const paths = ['/terminal', '/today', '/market', '/notifications', '/settings/profile', '/settings/data-licence', '/admin/users'];

beforeEach(() => {
  mockLoginAs('demo_user');
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
});

function renderAt(path = '/today') {
  const router = createMemoryRouter([
    { element: <AppShell />, children: paths.map((path) => ({ path, element: <h1>{path}</h1> })) },
    { path: '/login', element: <h1>登录页面</h1> },
  ], { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><TestRouterProvider router={router} /></AppProviders>);
}

describe('应用外壳', () => {
  it('保留页面内容和风险提示，主导航及品牌可返回终端', async () => {
    renderAt();
    expect(screen.getByRole('heading', { name: '/today' })).toBeInTheDocument();
    expect(screen.getByTestId('risk-disclosure')).toHaveTextContent('本工具仅供个人研究参考，不构成投资建议');
    const nav = within(screen.getByRole('navigation', { name: '主导航' }));
    expect(nav.getByRole('link', { name: '今日关注' })).toHaveAttribute('aria-current', 'page');
    fireEvent.click(nav.getByRole('link', { name: '交易终端' }));
    expect(await screen.findByRole('heading', { name: '/terminal' })).toBeInTheDocument();
    fireEvent.click(nav.getByRole('link', { name: '今日关注' }));
    await screen.findByRole('heading', { name: '/today' });
    fireEvent.click(screen.getByText('投资研究与决策助手'));
    expect(await screen.findByRole('heading', { name: '/terminal' })).toBeInTheDocument();
  });

  it('更多菜单可打开市场概览', async () => {
    renderAt();
    fireEvent.mouseEnter(screen.getByText('更多 ▾'));
    fireEvent.click(await screen.findByRole('menuitem', { name: '市场概览' }));
    expect(await screen.findByRole('heading', { name: '/market' })).toBeInTheDocument();
  });

  it.each([
    ['user', '投资画像', '/settings/profile'],
    ['admin', '用户审核（管理）', '/admin/users'],
  ] as const)('%s 用户菜单按权限提供入口并可导航', async (role, label, path) => {
    server.use(http.get(`${API}/me`, () => HttpResponse.json({ ...ME, role, display_name: '补测用户' })));
    renderAt();
    fireEvent.click(await screen.findByText('补测用户'));
    const menu = await screen.findByRole('menu');
    expect(within(menu).queryByRole('menuitem', { name: '用户审核（管理）' }) !== null).toBe(role === 'admin');
    fireEvent.click(within(menu).getByRole('menuitem', { name: label }));
    expect(await screen.findByRole('heading', { name: path })).toBeInTheDocument();
  });

  it('证书未设置时显示横幅，并能进入设置', async () => {
    server.use(http.get(`${API}/me`, () => HttpResponse.json({ ...ME, data_licence_status: 'not_set' })));
    renderAt();
    const banner = await screen.findByRole('status');
    expect(banner).toHaveTextContent('数据证书');
    fireEvent.click(within(banner).getByRole('button', { name: '去设置 ›' }));
    expect(await screen.findByRole('heading', { name: '/settings/data-licence' })).toBeInTheDocument();
  });

  it('通知为空时显示空态，并能打开通知中心', async () => {
    server.use(http.get(`${API}/notifications`, () => HttpResponse.json({ items: [], next_cursor: null })));
    renderAt();
    fireEvent.click(screen.getByRole('button', { name: '通知' }));
    expect(await screen.findByText('暂无通知')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '通知中心 ›' }));
    expect(await screen.findByRole('heading', { name: '/notifications' })).toBeInTheDocument();
  });

  it.each([
    ['未读且有目标', null, true],
    ['已读且有目标', '2026-11-02T10:41:00+08:00', true],
    ['未读且无目标', null, false],
  ] as const)('点击%s通知，仅未读项标记已读，有目标才跳转', async (_label, readAt, hasTarget) => {
    let reads = 0;
    const item: Notification = {
      ...NOTIFICATIONS[0], title: '补测通知', read_at: readAt,
      target: { type: 'none', id: null, route: null },
    };
    // 使用合法的站内通知深链，目标页作为外壳的测试子路由展示。
    if (hasTarget) item.target = { type: 'daily_report', id: '2026-11-02', route: '/daily-reports/2026-11-02' };
    server.use(
      http.get(`${API}/notifications`, () => HttpResponse.json({ items: [item], next_cursor: null })),
      http.post(`${API}/notifications/:id/read`, () => { reads++; item.read_at = '2026-11-02T10:42:00+08:00'; return new HttpResponse(null, { status: 204 }); }),
    );
    const router = createMemoryRouter([
      { element: <AppShell />, children: [
        { path: '/today', element: <h1>今日关注页面</h1> },
        { path: '/daily-reports/:date', element: <h1>日报详情</h1> },
      ] },
    ], { initialEntries: ['/today'] });
    render(<AppProviders client={makeQueryClient(true)}><TestRouterProvider router={router} /></AppProviders>);
    fireEvent.click(screen.getByRole('button', { name: '通知' }));
    fireEvent.click(await screen.findByText('补测通知'));
    expect(await screen.findByRole('heading', { name: hasTarget ? '日报详情' : '今日关注页面' })).toBeInTheDocument();
    await waitFor(() => expect(reads).toBe(readAt ? 0 : 1));
  });

  it('退出登录请求结束后显示登录页', async () => {
    const logout = vi.fn();
    server.use(http.post(`${API}/auth/logout`, () => { logout(); return new HttpResponse(null, { status: 204 }); }));
    renderAt();
    fireEvent.click(await screen.findByText('示例用户'));
    fireEvent.click(await screen.findByRole('menuitem', { name: '退出登录' }));
    expect(await screen.findByRole('heading', { name: '登录页面' })).toBeInTheDocument();
    expect(logout).toHaveBeenCalledOnce();
  });

  it('安全令牌失效时显示可关闭的刷新提示', async () => {
    server.use(http.get(`${API}/notifications/unread-count`, () => HttpResponse.json({ error: { code: 'CSRF_FAILED', message: '失效', details: null } }, { status: 403 })));
    renderAt();
    const alert = await screen.findByTestId('csrf-refresh');
    expect(alert).toHaveTextContent('刚才的操作没有提交');
    expect(within(alert).getByRole('button', { name: '刷新页面' })).toBeInTheDocument();
    fireEvent.click(within(alert).getByRole('button', { name: /close/i }));
    await waitFor(() => expect(screen.queryByTestId('csrf-refresh')).not.toBeInTheDocument());
  });
});
