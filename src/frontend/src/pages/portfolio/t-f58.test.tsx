import { act, fireEvent, renderHook, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { useCreateTrade, useTrades, useVoidTrade } from '../../api/accountQueries';
import type { Trade } from '../../api/accountTypes';
import { setCsrfToken } from '../../api/client';
import { ACCOUNT_ID, uid } from '../../mocks/fixtures';
import { errorBody } from '../../mocks/handlerUtils';
import { server } from '../../mocks/server';
import { SECOND_ACCOUNT_ID, state } from '../../mocks/session';
import { preloadRoutes } from '../../test/preloadRoutes';
import { renderAt } from '../../test/renderAt';

const API = '/api/v1/trades';
beforeAll(() => preloadRoutes(routes), 30_000);
afterEach(() => server.events.removeAllListeners());

function observeTrades() {
  const seen: URLSearchParams[] = [];
  server.events.on('request:start', ({ request }) => {
    const url = new URL(request.url);
    if (url.pathname === API && request.method === 'GET') seen.push(url.searchParams);
  });
  return seen;
}

function searchCode(value: string) {
  const input = screen.getByPlaceholderText('证券代码，如 600000.SH');
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 });
  fireEvent.keyUp(input, { key: 'Enter', code: 'Enter', keyCode: 13 });
}

function enterDate(placeholder: string, value: string) {
  const input = screen.getByPlaceholderText(placeholder);
  fireEvent.focus(input);
  fireEvent.change(input, { target: { value } });
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 });
  fireEvent.keyUp(input, { key: 'Enter', code: 'Enter', keyCode: 13 });
}

describe('T-F58 成交筛选与游标分页', () => {
  it('筛选传递规范化代码、日期和作废开关；清空后恢复完整列表', async () => {
    const base = state.trades[0];
    state.trades = [
      { ...base, id: uid(2001), security_code: '600000.SH', trade_date: '2026-10-20', name: '区间内' },
      { ...base, id: uid(2002), security_code: '600000.SH', trade_date: '2026-10-19', name: '区间外' },
      { ...base, id: uid(2003), security_code: '600000.SH', trade_date: '2026-10-21', name: '已作废记录', voided: true },
      { ...base, id: uid(2004), name: '其他证券' },
      { ...base, id: uid(2005), account_id: SECOND_ACCOUNT_ID, name: '其他账户' },
      { ...base, id: uid(2006), security_code: '600000.SH', trade_date: '2026-10-22', name: '区间后' },
    ];
    const seen = observeTrades();
    renderAt('/portfolio?tab=trades');
    await screen.findByTestId('portfolio-page');
    expect(await screen.findByText('区间内')).toBeInTheDocument();
    expect(seen[0].get('account_id')).toBe(ACCOUNT_ID);
    expect(seen[0].get('limit')).toBe('200');
    expect(seen[0].has('cursor')).toBe(false);
    expect(Object.fromEntries(seen[0])).toEqual({ account_id: ACCOUNT_ID, include_voided: 'true', limit: '200' });
    searchCode(' 600000.sh ');
    enterDate('开始日期', '2026-10-20');
    enterDate('结束日期', '2026-10-21');
    fireEvent.click(screen.getByRole('switch', { name: '含已作废' }));
    await waitFor(() => expect(seen.at(-1)?.toString()).toContain('include_voided=false'));
    expect(Object.fromEntries(seen.at(-1)!)).toEqual({
      account_id: ACCOUNT_ID, security_code: '600000.SH', from: '2026-10-20', to: '2026-10-21', include_voided: 'false', limit: '200',
    });
    await waitFor(() => expect(screen.getByTestId('trades-pager-end')).toHaveTextContent('全部 1 条'));
    expect(screen.queryByText('区间外')).not.toBeInTheDocument();
    expect(screen.queryByText('区间后')).not.toBeInTheDocument();
    expect(screen.queryByText('已作废记录')).not.toBeInTheDocument();
    expect(screen.queryByText('其他证券')).not.toBeInTheDocument();
    expect(screen.queryByText('其他账户')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('switch', { name: '含已作废' }));
    expect(await screen.findByText('已作废记录')).toBeInTheDocument();
    expect(screen.getByTestId('trades-pager-end')).toHaveTextContent('全部 2 条');
    searchCode('');
    fireEvent.click(screen.getByPlaceholderText('开始日期').closest('.ant-picker')!.querySelector('.ant-picker-clear')!);
    await waitFor(() => expect(screen.getByTestId('trades-pager-end')).toHaveTextContent('全部 5 条'));
    expect(screen.getByText('其他证券')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('开始日期')).toHaveValue('');
    expect(screen.getByPlaceholderText('结束日期')).toHaveValue('');
  });

  it('复用 /trades handler 加载第 201 条，末页停止请求', async () => {
    const base = state.trades[0];
    state.trades = Array.from({ length: 201 }, (_, i) => ({ ...base, id: uid(3000 - i), name: `成交第${i + 1}条` }));
    const seen = observeTrades();
    renderAt('/portfolio?tab=trades');
    expect(await screen.findByText('成交第200条')).toBeInTheDocument();
    expect(screen.queryByText('成交第201条')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('trades-pager-more'));
    expect(await screen.findByText('成交第201条')).toBeInTheDocument();
    expect(screen.getByTestId('trades-pager-end')).toHaveTextContent('全部 201 条');
    expect(screen.queryByTestId('trades-pager-more')).not.toBeInTheDocument();
    expect(seen.map((p) => p.get('cursor'))).toEqual([null, '200']);
  });

  it.each([503, 400])('下一页 %s 保留内容；重试原样发送不透明游标并按 id 去重', async (status) => {
    const base = state.trades[0];
    const cursor = 'opaque +/%?=&中文';
    const cursors: (string | null)[] = [];
    server.use(http.get(API, ({ request }) => {
      const c = new URL(request.url).searchParams.get('cursor');
      cursors.push(c);
      if (c === null) return HttpResponse.json({ items: [base], next_cursor: cursor });
      if (cursors.length === 2) return HttpResponse.json(errorBody(status === 400 ? 'INVALID_CURSOR' : 'INTERNAL_ERROR', '测试下一页失败'), { status });
      return HttpResponse.json({ items: [base, { ...base, id: uid(4001), name: '后续成交' }], next_cursor: null });
    }));
    renderAt('/portfolio?tab=trades');
    expect(await screen.findByText(base.name)).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('trades-pager-more'));
    expect(await screen.findByText('下一页加载失败，已加载的内容保留')).toBeInTheDocument();
    expect(screen.getByText(base.name)).toBeInTheDocument();
    expect(screen.queryByText('测试下一页失败')).not.toBeInTheDocument();
    fireEvent.click(within(screen.getByTestId('trades-pager')).getByRole('button', { name: /重\s*试/ }));
    expect(await screen.findByText('后续成交')).toBeInTheDocument();
    expect(screen.getAllByText(base.name)).toHaveLength(1);
    expect(screen.getByTestId('trades-pager-end')).toHaveTextContent('全部 2 条');
    expect(cursors).toEqual([null, cursor, cursor]);
  });

  it('翻页后改筛选从第一页请求，不混用旧游标和旧数据', async () => {
    const base = state.trades[0];
    const seen: URLSearchParams[] = [];
    server.use(http.get(API, ({ request }) => {
      const p = new URL(request.url).searchParams;
      seen.push(p);
      if (p.get('security_code')) return HttpResponse.json({ items: [{ ...base, id: uid(4002), name: '筛选成交' }], next_cursor: null });
      return HttpResponse.json({ items: [{ ...base, id: p.get('cursor') ? uid(4003) : base.id, name: p.get('cursor') ? '旧后续页' : '旧首页' }], next_cursor: p.get('cursor') ? null : '__proto__' });
    }));
    renderAt('/portfolio?tab=trades');
    await screen.findByText('旧首页');
    fireEvent.click(screen.getByTestId('trades-pager-more'));
    await screen.findByText('旧后续页');
    searchCode('600000.SH');
    expect(await screen.findByText('筛选成交')).toBeInTheDocument();
    expect(screen.queryByText('旧首页')).not.toBeInTheDocument();
    expect(screen.queryByText('旧后续页')).not.toBeInTheDocument();
    expect(seen.map((p) => p.get('cursor'))).toEqual([null, '__proto__', null]);
  });

  it('空态保留暂无成交，不显示分页按钮', async () => {
    state.trades = [];
    renderAt('/portfolio?tab=trades');
    expect(await screen.findByText('暂无成交')).toBeInTheDocument();
    expect(screen.queryByTestId('trades-pager')).not.toBeInTheDocument();
    expect(screen.queryByTestId('trades-pager-end')).not.toBeInTheDocument();
  });

  it('首屏错误保留 ErrorBox，不显示下一页错误提示', async () => {
    server.use(http.get(API, () => HttpResponse.json(errorBody('INTERNAL_ERROR', '成交首页不可用'), { status: 500 })));
    renderAt('/portfolio?tab=trades');
    expect(await screen.findByText(/服务内部错误/)).toBeInTheDocument();
    expect(screen.queryByTestId('trades-pager')).not.toBeInTheDocument();
    expect(screen.queryByText('下一页加载失败，已加载的内容保留')).not.toBeInTheDocument();
  });

  it.each(['not_a_side', '__proto__', 'constructor'])('未知方向 %s 显示中性色未知且页面不崩溃', async (side) => {
    state.trades = [{ ...state.trades[0], side: side as Trade['side'] }];
    renderAt('/portfolio?tab=trades');
    const label = await screen.findByText('未知');
    expect(label).toHaveClass('ant-tag-default');
    expect(screen.getByTestId('trades-tab')).toBeInTheDocument();
  });

  it('筛选缓存仍由手工录入、更正、作废的原失效前缀刷新', async () => {
    const client = makeQueryClient(true);
    const base = state.trades[0];
    const { result } = renderHook(() => ({
      trades: useTrades(ACCOUNT_ID, { security_code: base.security_code, include_voided: true }),
      create: useCreateTrade(), voidTrade: useVoidTrade(),
    }), { wrapper: ({ children }) => <AppProviders client={client}>{children}</AppProviders> });
    await waitFor(() => expect(result.current.trades.items).toHaveLength(1));
    setCsrfToken('mock-csrf');
    const body = { account_id: ACCOUNT_ID, trade_date: '2026-10-28', trade_time: null, security_code: base.security_code, side: 'buy' as const, qty: '100', price: '10', fee_total: null };
    await act(() => result.current.create.mutateAsync({ body, key: 't-f58-create' }));
    await waitFor(() => expect(result.current.trades.items).toHaveLength(2));
    await act(() => result.current.create.mutateAsync({ body: { ...body, corrects_trade_id: base.id, reason: '更正' }, key: 't-f58-correct' }));
    await waitFor(() => expect(result.current.trades.items.find((t) => t.id === base.id)?.voided).toBe(true));
    const created = result.current.trades.items.find((t) => t.id !== base.id && !t.corrects_trade_id)!;
    await act(() => result.current.voidTrade.mutateAsync({ id: created.id, reason: '作废' }));
    await waitFor(() => expect(result.current.trades.items.find((t) => t.id === created.id)?.voided).toBe(true));
    expect(result.current.trades.items).toHaveLength(3);
  });

  it('无账户不请求；省略筛选仍沿用原请求参数，切换账户不混入旧成交', async () => {
    const client = makeQueryClient(true);
    state.trades.push({ ...state.trades[0], id: uid(5001), account_id: SECOND_ACCOUNT_ID, name: '第二账户成交' });
    const seen = observeTrades();
    const { result, rerender } = renderHook(({ id }: { id: string | undefined }) => useTrades(id), {
      initialProps: { id: undefined as string | undefined },
      wrapper: ({ children }) => <AppProviders client={client}>{children}</AppProviders>,
    });
    expect(result.current.fetchStatus).toBe('idle');
    expect(seen).toHaveLength(0);
    rerender({ id: ACCOUNT_ID });
    await waitFor(() => expect(result.current.items).toHaveLength(6));
    expect(Object.fromEntries(seen[0])).toEqual({ account_id: ACCOUNT_ID, limit: '200' });
    rerender({ id: SECOND_ACCOUNT_ID });
    await waitFor(() => expect(result.current.items.map((t) => t.name)).toEqual(['第二账户成交']));
    expect(seen.at(-1)?.get('account_id')).toBe(SECOND_ACCOUNT_ID);
  });
});
