import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import type { ComponentType } from 'react';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';

type RestrictionKind = 'blocklist' | 'cooling_off' | 'mute';
type Restriction = {
  id: string;
  kind: RestrictionKind;
  target_type: 'security' | 'strategy' | 'instance';
  target_id: string;
  name: string | null;
  until: string | null;
  status: 'active' | 'expired';
};

const API = '/api/v1/restrictions';
const SYNTHETIC_ITEMS: Restriction[] = [
  { id: '00000000-0000-4000-8000-000000000701', kind: 'blocklist', target_type: 'security', target_id: 'SYN001.SH', name: null, until: null, status: 'active' },
  { id: '00000000-0000-4000-8000-000000000702', kind: 'cooling_off', target_type: 'strategy', target_id: 'SYN002', name: '合成策略', until: '2026-11-19T10:00:00+08:00', status: 'expired' },
];

let items: Restriction[] = [];
let postBodies: Record<string, unknown>[] = [];
let failGet = false;
let failPost = false;

function restrictionHandlers() {
  return [
    http.get(API, ({ request }) => {
      if (failGet) return HttpResponse.json({ error: { code: 'SYNTHETIC_GET_ERROR', message: '合成限制读取失败', details: null, request_id: 'synthetic-restrictions-get' } }, { status: 500 });
      const url = new URL(request.url);
      const kind = url.searchParams.get('kind');
      const targetType = url.searchParams.get('target_type');
      const filtered = items.filter((item) => (!kind || item.kind === kind) && (!targetType || item.target_type === targetType));
      return HttpResponse.json({ items: filtered, next_cursor: null });
    }),
    http.post(API, async ({ request }) => {
      const body = await request.json() as Record<string, unknown>;
      postBodies.push(body);
      if (failPost) return HttpResponse.json({ error: { code: 'SYNTHETIC_POST_ERROR', message: '合成限制保存失败', details: null, request_id: 'synthetic-restrictions-post' } }, { status: 500 });
      const created: Restriction = {
        id: '00000000-0000-4000-8000-000000000703',
        kind: body.kind as RestrictionKind,
        target_type: body.target_type as Restriction['target_type'],
        target_id: String(body.target_id),
        name: null,
        until: typeof body.until === 'string' ? body.until : null,
        status: 'active',
      };
      items = [...items, created];
      return HttpResponse.json(created, { status: 201 });
    }),
    http.delete(`${API}/:id`, ({ params }) => {
      items = items.filter((item) => item.id !== params.id);
      return HttpResponse.json({ deleted: true, gaps: [{ key: 'synthetic-recheck', reason: 'upstream_error', message: '合成重查尚未完成' }] });
    }),
  ];
}

const pageLoaders = import.meta.glob<Record<string, unknown>>('./RestrictionsPage.{tsx,ts}', { eager: false });
const pageLoader = Object.values(pageLoaders)[0];
const pageModule = pageLoader ? await pageLoader().catch(() => null) : null;
const RestrictionsPage = pageModule?.RestrictionsPage as ComponentType | undefined;
const restrictionsSuite = RestrictionsPage ? describe : describe.skip;

function renderRestrictions(search = '') {
  if (!RestrictionsPage) throw new Error('T-F68 未实现：RestrictionsPage 不存在');
  const router = createMemoryRouter([{ path: '/restrictions', element: <RestrictionsPage /> }], { initialEntries: [`/restrictions${search}`] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

function formInput(pattern: RegExp): HTMLInputElement {
  const labelled = screen.queryByLabelText(pattern);
  if (labelled instanceof HTMLInputElement) return labelled;
  const input = Array.from(document.querySelectorAll('input')).find((candidate) => pattern.test(candidate.getAttribute('placeholder') ?? '') || pattern.test(candidate.getAttribute('name') ?? ''));
  if (!(input instanceof HTMLInputElement)) throw new Error(`未找到表单输入 ${pattern}`);
  return input;
}

function chooseCoolingOff() {
  const labeled = screen.queryByLabelText('限制类型') ?? screen.queryByLabelText(/限制类型|类型/);
  const comboboxes = screen.getAllByRole('combobox');
  const select = labeled ?? comboboxes.find((candidate) => /kind|类型|限制/.test(candidate.getAttribute('aria-label') ?? candidate.getAttribute('name') ?? '')) ?? comboboxes[0];
  if (!select) throw new Error('未找到限制类型控件');
  if (select instanceof HTMLSelectElement) {
    fireEvent.change(select, { target: { value: 'cooling_off' } });
    return;
  }
  fireEvent.mouseDown(select);
  const option = screen.getByText('冷静期', { selector: '.ant-select-item-option-content' });
  fireEvent.click(option);
}

function submitButton() {
  const byId = document.querySelector('[data-testid="restriction-create"]');
  if (byId instanceof HTMLButtonElement) return byId;
  const buttons = screen.getAllByRole('button', { name: /新增|提交|保存|确认|创建/ });
  const button = buttons.at(-1);
  if (!button) throw new Error('未找到限制提交按钮');
  return button as HTMLButtonElement;
}

restrictionsSuite('T-F68 /restrictions 契约回归', () => {
  beforeEach(() => {
    mockLoginAs('demo_user');
    items = SYNTHETIC_ITEMS.map((item) => ({ ...item }));
    postBodies = [];
    failGet = false;
    failPost = false;
    server.use(...restrictionHandlers());
  });

  it('空列表可见空态且页面不崩', async () => {
    items = [];
    renderRestrictions();
    expect(await screen.findByText(/没有.*限制|暂无.*限制|限制.*为空|暂无/)).toBeInTheDocument();
  });

  it('展示目标标识、保留 until=null 并标出过期项', async () => {
    renderRestrictions();
    expect(await screen.findByText('SYN001.SH')).toBeInTheDocument();
    expect(screen.getByText('SYN002')).toBeInTheDocument();
    expect(screen.getByText(/过期|expired/)).toBeInTheDocument();
    expect(screen.queryByText(/2026-11-20|2026-11-21|2099/)).not.toBeInTheDocument();
  });

  it('按 kind 查询只展示匹配的限制项', async () => {
    renderRestrictions('?kind=blocklist');
    expect(await screen.findByText('SYN001.SH')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('SYN002')).not.toBeInTheDocument());
  });

  it('冷静期没有未来 until 不能提交，填写未来 until 后 POST 不带 user_id', async () => {
    renderRestrictions();
    await screen.findByText('SYN001.SH');
    const add = screen.queryByRole('button', { name: /新增|添加|创建/ });
    if (add) fireEvent.click(add);
    chooseCoolingOff();
    const target = formInput(/目标.*(ID|标识)|target/i);
    fireEvent.change(target, { target: { value: 'SYN003.SH' } });
    const submit = submitButton();
    fireEvent.click(submit);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(postBodies).toHaveLength(0);
    expect(submit.disabled || Boolean(screen.queryByText(/未来|截止|必填|校验/))).toBe(true);

    const until = formInput(/截止|until/i);
    fireEvent.change(until, { target: { value: '2099-12-31T15:00' } });
    fireEvent.click(submit);
    await waitFor(() => expect(postBodies).toHaveLength(1));
    expect(postBodies[0]).not.toHaveProperty('user_id');
    expect(typeof postBodies[0].until).toBe('string');
    expect(Date.parse(String(postBodies[0].until))).toBeGreaterThan(Date.parse('2026-11-20T10:00:00+08:00'));
  });

  it('GET 错误可见且页面不白屏', async () => {
    failGet = true;
    renderRestrictions();
    const getAlerts = await screen.findAllByRole('alert');
    expect(getAlerts.length).toBeGreaterThan(0);
    expect(getAlerts[0]).toHaveTextContent(/读取失败|加载失败|SYNTHETIC_GET_ERROR/);
  });

  it('POST 错误可见', async () => {
    failPost = true;
    renderRestrictions();
    await screen.findByText('SYN001.SH');
    const add = screen.queryByRole('button', { name: /新增|添加|创建/ });
    if (add) fireEvent.click(add);
    const target = formInput(/目标.*(ID|标识)|target/i);
    fireEvent.change(target, { target: { value: 'SYN003.SH' } });
    const submit = submitButton();
    fireEvent.click(submit);
    await waitFor(() => expect(postBodies).toHaveLength(1));
    const postAlerts = await screen.findAllByRole('alert');
    expect(postAlerts.length).toBeGreaterThan(0);
    expect(postAlerts[0]).toHaveTextContent(/保存失败|加载失败|SYNTHETIC_POST_ERROR/);
  });

  it('删除说明保留不可交易语义，DELETE 带 gaps 时页面不崩', async () => {
    renderRestrictions();
    await screen.findByText('SYN001.SH');
    expect(screen.getByText(/删除成功.*可交易|可交易.*删除|系统重查|重新检查/)).toBeInTheDocument();
    const deleteButton = document.querySelector('[data-testid^="restriction-delete-"]')
      ?? screen.getAllByRole('button').find((button) => button.textContent?.includes('删除') && !button.textContent.includes('不等于'));
    if (!deleteButton) throw new Error('未找到删除按钮');
    fireEvent.click(deleteButton);
    const confirm = screen.queryByRole('button', { name: /确认删除|确定/ });
    if (confirm) fireEvent.click(confirm);
    await waitFor(() => expect(screen.queryByText('SYN001.SH')).not.toBeInTheDocument());
  });
});

if (!RestrictionsPage) {
  it.fails('T-F68 未实现：RestrictionsPage 动态导入应在落地后转为普通用例', async () => {
    throw new Error('T-F68 未实现：RestrictionsPage 不存在');
  });
}
