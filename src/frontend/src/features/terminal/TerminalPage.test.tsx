import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { TerminalResponse } from '../../api/types';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { SIGNAL_EVENTS, TERMINAL_ACCOUNT, TERMINAL_ROWS } from '../../mocks/fixtures';
import { errorBody } from '../../mocks/handlerUtils';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { TerminalPage } from './TerminalPage';

// 与现有终端测试一致，仅替换依赖真实 canvas 的图表。
vi.mock('../../components/charts/KlineChart', () => ({ KlineChart: () => <div>日 K 图</div> }));
vi.mock('../../components/charts/IntradayChart', () => ({ IntradayChart: () => <div>分时图</div> }));

const rows = TERMINAL_ROWS.slice(0, 2);
const body: TerminalResponse = {
  account_id: TERMINAL_ACCOUNT.account_id,
  server_time: '2026-11-02T02:31:00Z', trade_date: '2026-11-02', session: 'morning',
  account: TERMINAL_ACCOUNT, rows, truncated: true, unread_notifications: 0,
};
beforeEach(() => {
  mockLoginAs('demo_user');
  server.use(http.get('/api/v1/terminal', () => HttpResponse.json(body)));
});
afterEach(() => vi.restoreAllMocks());

function renderTerminal() {
  const router = createMemoryRouter([
    { path: '/terminal', element: <TerminalPage /> },
    { path: '/suggestions/:id', element: <h1>候选信号详情</h1> },
  ], { initialEntries: ['/terminal'] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('T-F51 交易终端', () => {
  it('默认选中首只证券，单击切换图表和信号卡', async () => {
    renderTerminal();
    expect(await screen.findByTestId('quote-head')).toHaveTextContent(rows[0].name);
    expect(screen.getByText(/服务器时间 2026-11-02 10:31/)).toHaveTextContent('列表已截断');
    expect(screen.getByTestId('account-strip')).toHaveTextContent('总资产');
    const table = screen.getByTestId('watch-table');
    const second = await within(table).findByText(rows[1].name, { exact: false });
    fireEvent.click(second);
    await waitFor(() => expect(screen.getByTestId('quote-head')).toHaveTextContent(rows[1].security_code));
    expect(screen.getByText(`候选信号卡 · ${rows[1].name}`)).toBeInTheDocument();
  });

  it('双击证券行打开对应的候选信号详情', async () => {
    const user = userEvent.setup();
    const router = renderTerminal();
    const first = await within(screen.getByTestId('watch-table')).findByText(rows[0].name, { exact: false });
    await user.dblClick(first);
    expect(await screen.findByRole('heading', { name: '候选信号详情' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(`/suggestions/${rows[0].suggestion!.id}`);
  });

  it('切换范围后显示对应列表，原选中证券消失时回退到首只', async () => {
    server.use(http.get('/api/v1/terminal', ({ request }) => {
      const scope = new URL(request.url).searchParams.get('scope');
      return HttpResponse.json({ ...body, rows: scope === 'all' ? rows : [rows[1]], truncated: false });
    }));
    renderTerminal();
    expect(await screen.findByTestId('quote-head')).toHaveTextContent(rows[0].security_code);
    fireEvent.click(screen.getByText('持仓', { exact: true }));
    await waitFor(() => expect(screen.getByTestId('quote-head')).toHaveTextContent(rows[1].security_code));
    expect(screen.queryByText(/列表已截断/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('自选', { exact: true }));
    expect(await within(screen.getByTestId('watch-table')).findByText(rows[1].name, { exact: false })).toBeInTheDocument();
  });

  it('点击底部规则事件同步选中的证券', async () => {
    const event = { ...SIGNAL_EVENTS[0], security_code: rows[1].security_code, name: rows[1].name, message: '测试证券的规则事件' };
    server.use(http.get('/api/v1/signals', () => HttpResponse.json({ items: [event], next_cursor: null })));
    renderTerminal();
    expect(await screen.findByTestId('quote-head')).toHaveTextContent(rows[0].security_code);
    fireEvent.click(await screen.findByText(event.message));
    await waitFor(() => expect(screen.getByTestId('quote-head')).toHaveTextContent(rows[1].security_code));
  });

  it('空列表提示选择证券，账户为空时显示未选择账户', async () => {
    server.use(http.get('/api/v1/terminal', () => HttpResponse.json({ ...body, rows: [], account: null })));
    renderTerminal();
    await screen.findByText(/服务器时间 2026-11-02 10:31/);
    expect(await screen.findByText('请选择左侧的一只证券')).toBeInTheDocument();
    expect(screen.getByText('未选择账户')).toBeInTheDocument();
    expect(screen.queryByTestId('quote-head')).not.toBeInTheDocument();
  });

  it('终端请求失败给出错误提示并保留工具栏', async () => {
    server.use(http.get('/api/v1/terminal', () => HttpResponse.json(errorBody('INTERNAL_ERROR', '读取失败'), { status: 500 })));
    renderTerminal();
    expect(await screen.findByRole('alert')).toHaveTextContent('服务内部错误，请稍后重试');
    expect(screen.getByRole('button', { name: /恢复默认布局/ })).toBeEnabled();
  });

  it('侧栏和底部面板可收起、展开，恢复默认布局重新展开各栏', async () => {
    // jsdom 没有布局测量，为真实分栏组件提供容器尺寸。
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(1200);
    vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(800);
    const user = userEvent.setup();
    renderTerminal();
    await screen.findByTestId('quote-head');
    for (const [name, title] of [['切换左栏', '展开左栏'], ['切换右栏', '展开右栏'], ['切换底部面板', '展开底部面板']]) {
      const button = screen.getByRole('button', { name });
      await user.click(button);
      await user.unhover(button);
      await user.hover(button);
      await waitFor(() => expect(screen.getAllByRole('tooltip').some((tip) => tip.textContent === title)).toBe(true));
      await user.unhover(button);
      await user.click(button);
    }
    await user.click(screen.getByRole('button', { name: '切换左栏' }));
    await user.click(screen.getByRole('button', { name: /恢复默认布局/ }));
    await user.hover(screen.getByRole('button', { name: '切换左栏' }));
    await waitFor(() => expect(screen.getAllByRole('tooltip').some((tip) => tip.textContent === '收起左栏')).toBe(true));
  });
});
