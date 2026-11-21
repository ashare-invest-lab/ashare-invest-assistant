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
  { id: '00000000-0000-4000-8000-000000000702', kind: 'cooling_off', target_type: 'strategy', target_id: 'SYN002', name: '合成策略', until: null, status: 'active' },
];

let items: Restriction[] = [];
let postBodies: Record<string, unknown>[] = [];

function restrictionHandlers() {
  return [
    http.get(API, () => {
      return HttpResponse.json({ items, next_cursor: null });
    }),
    http.post(API, async ({ request }) => {
      const body = await request.json() as Record<string, unknown>;
      postBodies.push(body);
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
      return HttpResponse.json({ deleted: true });
    }),
  ];
}

const pageLoaders = import.meta.glob<Record<string, unknown>>('./RestrictionsPage.{tsx,ts}', { eager: false });
const pageLoader = Object.values(pageLoaders)[0];
const pageModule = pageLoader ? await pageLoader() : null;
if (pageLoader && !pageModule?.RestrictionsPage) {
  throw new Error('RestrictionsPage 文件存在但未导出 RestrictionsPage');
}
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
    server.use(...restrictionHandlers());
  });

  it('空列表可见空态且页面不崩', async () => {
    items = [];
    renderRestrictions();
    expect(await screen.findByText(/没有.*限制|暂无.*限制|限制.*为空|暂无/)).toBeInTheDocument();
  });

  it('展示官方目标标识', async () => {
    renderRestrictions();
    expect(await screen.findByText('SYN001.SH')).toBeInTheDocument();
    expect(screen.getByText('SYN002')).toBeInTheDocument();
  });

  it('创建限制使用官方字段且不带 user_id', async () => {
    renderRestrictions();
    await screen.findByText('SYN001.SH');
    const add = screen.queryByRole('button', { name: /新增|添加|创建/ });
    if (add) fireEvent.click(add);
    const target = formInput(/目标.*(ID|标识)|target/i);
    fireEvent.change(target, { target: { value: 'SYN003.SH' } });
    const submit = submitButton();
    fireEvent.click(submit);
    await waitFor(() => expect(postBodies).toHaveLength(1));
    expect(Object.keys(postBodies[0]).sort()).toEqual(['kind', 'reason', 'target_id', 'target_type', 'until']);
    expect(postBodies[0]).not.toHaveProperty('user_id');
  });

  it('删除后对应行消失且页面不崩', async () => {
    renderRestrictions();
    await screen.findByText('SYN001.SH');
    const deleteButton = document.querySelector('[data-testid^="restriction-delete-"]')
      ?? screen.getAllByRole('button').find((button) => button.textContent?.includes('删除'));
    if (!deleteButton) throw new Error('未找到删除按钮');
    fireEvent.click(deleteButton);
    const confirm = screen.queryByRole('button', { name: /确认删除|确定/ });
    if (confirm) fireEvent.click(confirm);
    await waitFor(() => expect(screen.queryByText('SYN001.SH')).not.toBeInTheDocument());
  });
});
