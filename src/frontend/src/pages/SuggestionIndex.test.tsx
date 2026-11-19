import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { delay, http, HttpResponse } from 'msw';
import { createMemoryRouter } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import type { SuggestionListItem } from '../api/types';
import { SUGGESTION_LIST } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { TestRouterProvider } from '../test/TestRouterProvider';
import { SuggestionIndex } from './SuggestionIndex';

const API = '/api/v1/suggestions';
const first: SuggestionListItem = {
  ...SUGGESTION_LIST[0], name: '补测银行', created_at: '2026-11-02T02:40:00Z',
  top_score: 88, consensus: 'single', executability_status: 'executable',
  actions: [{ strategy_key: 'test', strategy_name: '趋势规则', action: 'buy', t_leg: null, lifecycle: 'simulating' }],
};
const second: SuggestionListItem = {
  ...first, id: 'second-card', name: '补测科技', top_score: null, status: 'expired',
  actions: [], consensus: 'none', executability_status: 'blocked',
};

beforeEach(() => mockLoginAs('demo_user'));

function renderAt(search = '') {
  const router = createMemoryRouter([
    { path: '/suggestions', element: <SuggestionIndex /> },
    { path: '/suggestions/:id', element: <h1>候选信号卡详情</h1> },
  ], { initialEntries: [`/suggestions${search}`] });
  render(<AppProviders client={makeQueryClient(true)}><TestRouterProvider router={router} /></AppProviders>);
  return router;
}

describe('候选信号卡列表', () => {
  it('加载后展示各列内容，追加下一页并可打开详情', async () => {
    const cursors: (string | null)[] = [];
    server.use(http.get(API, async ({ request }) => {
      const cursor = new URL(request.url).searchParams.get('cursor');
      cursors.push(cursor);
      await delay(30);
      if (cursor === null) return HttpResponse.json({ items: [first], next_cursor: 'page-2' });
      if (cursor === 'page-2') return HttpResponse.json({ items: [second], next_cursor: null });
      return new HttpResponse(null, { status: 400 });
    }));
    renderAt();
    expect(screen.getByText('加载中…')).toBeInTheDocument();
    const link = await screen.findByRole('link', { name: /补测银行/ });
    expect(cursors).toEqual([null]);
    expect(link).toHaveAttribute('href', `/suggestions/${first.id}`);
    const row = within(link.closest('tr')!);
    for (const text of ['2026-11-02 10:40', '当前', '单策略', '88', '可执行']) {
      expect(row.getByText(text)).toBeInTheDocument();
    }
    expect(row.getByText(/模拟中/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '加载更多' }));
    const next = await screen.findByRole('link', { name: /补测科技/ });
    expect(cursors).toEqual([null, 'page-2']);
    expect(within(next.closest('tr')!).getByText('—')).toBeInTheDocument();
    expect(within(next.closest('tr')!).getByText('已过期')).toBeInTheDocument();
    expect(within(next.closest('tr')!).getByText('暂不可执行')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /补测银行/ })).toBeInTheDocument();
    expect(screen.getByText('已显示全部 2 条')).toBeInTheDocument();
    fireEvent.click(link);
    expect(await screen.findByRole('heading', { name: '候选信号卡详情' })).toBeInTheDocument();
  });

  it('修改状态和代码筛选会更新 URL、查询及空态，清空后恢复列表', async () => {
    const searches: URLSearchParams[] = [];
    server.use(http.get(API, ({ request }) => {
      const params = new URL(request.url).searchParams;
      searches.push(params);
      return HttpResponse.json({ items: params.has('security_code') ? [] : [first], next_cursor: null });
    }));
    const router = renderAt();
    await screen.findByRole('link', { name: /补测银行/ });
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '卡片状态' }));
    fireEvent.click(await screen.findByText('已失效', { selector: '.ant-select-item-option-content' }));
    await waitFor(() => expect(searches.at(-1)?.get('status')).toBe('invalidated'));
    fireEvent.change(screen.getByRole('searchbox', { name: '证券代码筛选' }), { target: { value: ' 600000.sh ' } });
    fireEvent.keyDown(screen.getByRole('searchbox', { name: '证券代码筛选' }), { key: 'Enter', keyCode: 13 });
    expect(await screen.findByText('当前筛选没有候选信号卡')).toBeInTheDocument();
    expect(new URLSearchParams(router.state.location.search).get('security_code')).toBe('600000.SH');
    expect(searches.at(-1)?.get('security_code')).toBe('600000.SH');
    expect(searches.at(-1)?.get('status')).toBe('invalidated');
    fireEvent.change(screen.getByRole('searchbox', { name: '证券代码筛选' }), { target: { value: '' } });
    fireEvent.keyDown(screen.getByRole('searchbox', { name: '证券代码筛选' }), { key: 'Enter', keyCode: 13 });
    expect(await screen.findByRole('link', { name: /补测银行/ })).toBeInTheDocument();
    expect(new URLSearchParams(router.state.location.search).has('security_code')).toBe(false);
  });

  it.each(['?status=invalid', '?security_code=not-a-code'])('非法筛选 %s 显示提示且不发送列表请求', async (search) => {
    const requested = vi.fn();
    server.use(http.get(API, () => { requested(); return HttpResponse.json({ items: [], next_cursor: null }); }));
    renderAt(search);
    expect(await screen.findByText('筛选参数格式不正确')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    // 跨过任务队列边界并刷新 React 更新，让误发的请求有机会进入 MSW。
    await act(async () => { await delay(0); });
    expect(requested).not.toHaveBeenCalled();
  });

  it('接口失败显示错误，不伪装成无数据', async () => {
    server.use(http.get(API, () => HttpResponse.json({ error: { code: 'INTERNAL_ERROR', message: '失败', details: null } }, { status: 500 })));
    renderAt();
    expect(await screen.findByRole('alert')).toHaveTextContent('服务内部错误，请稍后重试');
    expect(screen.queryByText('当前筛选没有候选信号卡')).not.toBeInTheDocument();
  });
});
