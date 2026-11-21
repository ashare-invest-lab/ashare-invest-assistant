import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import type { NonExecutableReason, Restriction } from '../../api/types';
import { server } from '../../mocks/server';
import { ReasonCard } from '../signals/ReasonCard';
import { RestrictionsPage } from './RestrictionsPage';

const API = '/api/v1';

function renderPage(path = '/restrictions') {
  const router = createMemoryRouter([{ path: '/restrictions', element: <RestrictionsPage /> }], { initialEntries: [path] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('T-F68 限制管理页', () => {
  it('列表显示禁投、冷静期、屏蔽和已过期项', async () => {
    renderPage();
    expect(await screen.findByTestId('restrictions-page')).toBeInTheDocument();
    expect(await screen.findByText('禁投')).toBeInTheDocument();
    expect((await screen.findAllByText('冷静期')).length).toBeGreaterThanOrEqual(1);
    expect(await screen.findByText('屏蔽')).toBeInTheDocument();
    expect(await screen.findByText('已过期')).toBeInTheDocument();
    expect(await screen.findByText('示例银行')).toBeInTheDocument();
  });

  it('空列表显示明确空态，且可以按类型筛选并写入 URL', async () => {
    server.use(http.get(`${API}/restrictions`, () => HttpResponse.json({ items: [], next_cursor: null })));
    renderPage();
    expect(await screen.findByText('暂无限制项。你可以在上方新增禁投、冷静期或屏蔽。')).toBeInTheDocument();
    server.resetHandlers();
    const filtered = renderPage();
    const select = screen.getAllByRole('combobox', { name: '筛选类型' }).at(-1);
    expect(select).toBeTruthy();
    fireEvent.mouseDown(select!);
    fireEvent.click(await screen.findByText('冷静期', { selector: '.ant-select-item-option-content' }));
    await waitFor(() => expect(new URLSearchParams(filtered.state.location.search).get('kind')).toBe('cooling_off'));
  });

  it('冷静期缺少未来截止时间时不可提交，补齐后新增项进入列表', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId('restrictions-page');
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '限制类型' }));
    fireEvent.click(await screen.findByText('冷静期', { selector: '.ant-select-item-option-content' }));
    expect(screen.getByTestId('restriction-create')).toBeDisabled();
    await user.type(screen.getByLabelText('目标 ID'), 'strategy-example-new');
    fireEvent.change(screen.getByLabelText('截止时间'), { target: { value: '2099-12-31T23:00' } });
    expect(screen.getByTestId('restriction-create')).toBeEnabled();
    await user.click(screen.getByTestId('restriction-create'));
    expect(await screen.findByText('strategy-example-new')).toBeInTheDocument();
  });

  it('删除后默认列表不再显示该行，页面没有把删除说成可交易', async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByText('示例银行');
    await user.click(screen.getByTestId('restriction-delete-restriction-example-block'));
    await waitFor(() => expect(screen.queryByText('示例银行')).not.toBeInTheDocument());
    expect(screen.queryByText('已可交易')).not.toBeInTheDocument();
  });

  it('未知枚举和值域原型键安全显示未知', async () => {
    const unknown: Restriction = {
      id: 'restriction-unknown', kind: '__proto__' as Restriction['kind'], target_type: 'constructor' as Restriction['target_type'],
      target_id: 'example-unknown', until: null, reason: null, created_at: '2026-11-20T12:00:00+08:00', name: null, status: '__proto__', removed_at: null,
    };
    const unfamiliar: Restriction = {
      id: 'restriction-unfamiliar', kind: 'unfamiliar-kind' as Restriction['kind'], target_type: 'unfamiliar-target' as Restriction['target_type'],
      target_id: 'example-unfamiliar', until: null, reason: null, created_at: '2026-11-20T12:00:00+08:00', name: null, status: 'unfamiliar-status', removed_at: null,
    };
    server.use(http.get(`${API}/restrictions`, () => HttpResponse.json({ items: [unknown, unfamiliar], next_cursor: null, gaps: [] })));
    renderPage();
    expect(await screen.findAllByText('未知')).toHaveLength(6);
    expect(screen.getByText('example-unknown')).toBeInTheDocument();
    expect(screen.getByText('example-unfamiliar')).toBeInTheDocument();
  });

  it('缺少服务端 status 时不会按已过期 until 推断状态', async () => {
    const missingStatus = {
      id: 'restriction-missing-status', kind: 'cooling_off', target_type: 'security', target_id: 'example-missing-status',
      name: '示例缺失状态', until: '2020-01-01T00:00:00+08:00', reason: null, created_at: '2026-11-20T12:00:00+08:00', removed_at: null,
    } as Omit<Restriction, 'status'>;
    server.use(http.get(`${API}/restrictions`, () => HttpResponse.json({ items: [missingStatus], next_cursor: null, gaps: [] })));
    renderPage();
    expect(await screen.findByText('example-missing-status')).toBeInTheDocument();
    expect(screen.getByText('未知')).toBeInTheDocument();
    expect(screen.queryByText('已过期')).not.toBeInTheDocument();
  });

  it('名单类仍生效原因提供限制名单链接', () => {
    const reason: NonExecutableReason = {
      id: 'reason-example', signal_id: 'signal-example', security_code: '600000.SH', name: '示例银行', code: 'BLOCKLISTED',
      description: '示例限制', evidence: [], status: 'active', detected_at: '2026-11-20T12:00:00+08:00', released_at: null,
      release_evidence: null, released_by: 'system',
      release_condition: { kind: 'user_action', expr: null, at: null, event: null, action: null, check_on: ['user_action'], human_text: '从限制名单移除后重查', machine_checkable: true },
    };
    render(<MemoryRouter><ReasonCard r={reason} /></MemoryRouter>);
    expect(screen.getByTestId('restriction-link-reason-example')).toHaveAttribute('href', '/restrictions');
  });

  it('/restrictions 路由渲染管理页而非占位页', async () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/restrictions'] });
    render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
    expect(await screen.findByTestId('restrictions-page')).toBeInTheDocument();
    expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();
  });
});
