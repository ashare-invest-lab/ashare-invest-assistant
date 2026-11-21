import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { draftsNow } from '../../mocks/planHandlers';
import { errorBody } from '../../mocks/handlerUtils';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { PlanDraftsPage } from './PlanDraftsPage';

function renderDrafts(search = '') {
  mockLoginAs('demo_user');
  const router = createMemoryRouter([
    { path: '/plan-drafts', element: <PlanDraftsPage /> },
    { path: '/plan-drafts/:id', element: <h2>草案详情</h2> },
  ], { initialEntries: [`/plan-drafts${search}`] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

it('草案展示数量、价格、估算亏损与北京时间，点击证券进入详情', async () => {
  const draft = { ...draftsNow()[0], name: '补测草案', valid_until: null };
  server.use(http.get('/api/v1/plan-drafts', () => HttpResponse.json({ items: [draft], next_cursor: null })));
  renderDrafts();
  const link = await screen.findByRole('link', { name: /补测草案/ });
  const row = within(link.closest('tr')!);
  expect(row.getByText('待确认')).toBeInTheDocument();
  expect(row.getByText(`${draft.qty_range.min}–${draft.qty_range.max}`)).toBeInTheDocument();
  expect(row.getByText(`${draft.price_range.low}–${draft.price_range.high}`)).toBeInTheDocument();
  expect(row.getByText(`(${draft.max_loss_pct}%)`)).toBeInTheDocument();
  expect(row.getByText('—')).toBeInTheDocument();
  expect(row.getByText('11-02 10:12:30')).toBeInTheDocument();
  fireEvent.click(link);
  expect(await screen.findByRole('heading', { name: '草案详情' })).toBeInTheDocument();
});

it('输入证券代码后规范化筛选，清空后恢复列表并保留状态筛选', async () => {
  const router = renderDrafts('?status=pending');
  await screen.findByTestId('drafts-pager-end');
  const input = screen.getByPlaceholderText('证券代码，如 600000.SH');
  fireEvent.change(input, { target: { value: ' 000000.sz ' } });
  fireEvent.keyDown(input, { key: 'Enter', code: 'Enter', keyCode: 13 });
  expect(await screen.findByText('没有符合条件的计划草案')).toBeInTheDocument();
  expect(new URLSearchParams(router.state.location.search).get('security_code')).toBe('000000.SZ');
  expect(new URLSearchParams(router.state.location.search).get('status')).toBe('pending');
  const filteredInput = screen.getByPlaceholderText('证券代码，如 600000.SH');
  fireEvent.change(filteredInput, { target: { value: '' } });
  fireEvent.keyDown(filteredInput, { key: 'Enter', code: 'Enter', keyCode: 13 });
  expect(await screen.findByTestId('drafts-pager-end')).toHaveTextContent('已显示全部 2 条');
  expect(new URLSearchParams(router.state.location.search).has('security_code')).toBe(false);
});

it('选择状态后显示对应草案，移除所选状态恢复全部', async () => {
  const router = renderDrafts();
  await screen.findByTestId('drafts-pager-end');
  fireEvent.mouseDown(screen.getByRole('combobox'));
  fireEvent.click(await screen.findByText('已确认', { selector: '.ant-select-item-option-content' }));
  expect(await screen.findByText('没有符合条件的计划草案')).toBeInTheDocument();
  expect(new URLSearchParams(router.state.location.search).get('status')).toBe('confirmed');
  fireEvent.click(within(screen.getByTestId('filter-status')).getByRole('button', { name: 'Clear' }));
  expect(await screen.findByTestId('drafts-pager-end')).toHaveTextContent('已显示全部 5 条');
  expect(new URLSearchParams(router.state.location.search).has('status')).toBe(false);
});

it('关闭候选信号筛选标签后恢复其他信号的草案', async () => {
  const router = renderDrafts(`?signal_id=${draftsNow()[0].signal_ids[0]}&status=pending`);
  expect(await screen.findByTestId('drafts-pager-end')).toHaveTextContent('已显示全部 1 条');
  fireEvent.click(within(screen.getByTestId('filter-signal')).getByRole('button', { name: '关闭' }));
  expect(await screen.findByTestId('drafts-pager-end')).toHaveTextContent('已显示全部 2 条');
  expect(new URLSearchParams(router.state.location.search).has('signal_id')).toBe(false);
  expect(new URLSearchParams(router.state.location.search).get('status')).toBe('pending');
});

it('加载更多保留首屏草案并显示新增草案与有效时间', async () => {
  const [first, second] = draftsNow();
  server.use(http.get('/api/v1/plan-drafts', ({ request }) => HttpResponse.json(
    new URL(request.url).searchParams.get('cursor')
      ? { items: [{ ...second, name: '下一页草案' }], next_cursor: null }
      : { items: [{ ...first, name: '第一页草案' }], next_cursor: 'next' },
  )));
  renderDrafts();
  expect(await screen.findByRole('link', { name: /第一页草案/ })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '加载更多' }));
  expect(await screen.findByRole('link', { name: /下一页草案/ })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /第一页草案/ })).toBeInTheDocument();
  expect(screen.getAllByText('11-02 15:00')).toHaveLength(2);
  expect(screen.getByTestId('drafts-pager-end')).toHaveTextContent('已显示全部 2 条');
});

it('接口失败时显示错误说明与请求编号，筛选控件仍可用', async () => {
  server.use(http.get('/api/v1/plan-drafts', () => HttpResponse.json(
    errorBody('INTERNAL_ERROR', '草案读取失败'), { status: 500 },
  )));
  renderDrafts();
  expect(await screen.findByRole('alert')).toHaveTextContent('INTERNAL_ERROR');
  expect(screen.getByRole('alert')).toHaveTextContent(/mock-\d+/);
  await waitFor(() => expect(screen.getByPlaceholderText('证券代码，如 600000.SH')).toBeEnabled());
});
