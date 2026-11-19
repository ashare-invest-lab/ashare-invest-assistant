import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { Plan } from '../../api/planAlertTypes';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { uid } from '../../mocks/fixtures';
import { errorBody } from '../../mocks/handlerUtils';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { apiFetch } from '../../test/apiFetch';
import { PlanDetailPage } from './PlanDetailPage';

const ACTIVE = uid(7303);
beforeEach(() => mockLoginAs('demo_user'));

function renderPlan(id = ACTIVE) {
  const router = createMemoryRouter([
    { path: '/plans/:id', element: <PlanDetailPage /> },
    { path: '/plans', element: <h1>计划列表</h1> },
  ], { initialEntries: [`/plans/${id}`] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

async function edit() {
  fireEvent.click(await screen.findByRole('button', { name: '修改计划（新建版本）' }));
  const drawer = await screen.findByRole('dialog');
  fireEvent.change(within(drawer).getByLabelText('修改原因'), { target: { value: '更新研究依据' } });
  return drawer;
}

describe('T-F51 计划详情的版本与关闭流程', () => {
  it('历史版本可以展开、收起，创建时间固定显示北京时间', async () => {
    renderPlan(uid(7301));
    expect(await screen.findByText(/2026-10-28 15:10（北京时间）/)).toBeInTheDocument();
    const history = screen.getByTestId('plan-versions');
    fireEvent.click(await within(history).findByRole('button', { name: '第 1 版' }));
    expect(within(history).getByText('价格低于或等于 22.80')).toBeInTheDocument();
    fireEvent.click(within(history).getByRole('button', { name: '第 1 版' }));
    expect(within(history).queryByText('价格低于或等于 22.80')).not.toBeInTheDocument();
  });

  it('保存新版本后更新当前依据，历史仍可回看；返回计划列表', async () => {
    renderPlan();
    const drawer = await edit();
    fireEvent.change(within(drawer).getByLabelText('计划依据'), { target: { value: '补充公告后的研究依据' } });
    fireEvent.click(within(drawer).getByRole('button', { name: '保存为新版本' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByText('当前版本（第 2 版）')).toBeInTheDocument();
    expect(screen.getByTestId('plan-current')).toHaveTextContent('补充公告后的研究依据');
    expect(await within(screen.getByTestId('plan-versions')).findByText('更新研究依据', { exact: false })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /操作计划/ }));
    expect(await screen.findByRole('heading', { name: '计划列表' })).toBeInTheDocument();
  });

  it('并发修改冲突明确告知未保存，载入最新版本后关闭编辑抽屉', async () => {
    let latest = await (await apiFetch(`/api/v1/plans/${ACTIVE}`)).json() as Plan;
    server.use(
      http.get('/api/v1/plans/:id', () => HttpResponse.json(latest)),
      http.get('/api/v1/plans/:id/versions', () => HttpResponse.json({ items: [latest.current_version], next_cursor: null })),
      http.post('/api/v1/plans/:id/versions', () => {
        latest = { ...latest, current_version_no: 2, version_count: 2,
          current_version: { ...latest.current_version, version_no: 2, rationale: '他处保存的新依据' } };
        return HttpResponse.json(errorBody('VERSION_CONFLICT', '计划已被修改', { current_version_no: 2 }), { status: 409 });
      }),
    );
    renderPlan();
    const drawer = await edit();
    fireEvent.click(within(drawer).getByRole('button', { name: '保存为新版本' }));
    expect(await screen.findByText('计划已被修改（当前为第 2 版），本次修改没有保存。')).toBeInTheDocument();
    expect(within(drawer).getByLabelText('修改原因')).toHaveValue('更新研究依据');
    fireEvent.click(screen.getByRole('button', { name: '载入最新版本' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByText('当前版本（第 2 版）')).toBeInTheDocument();
    expect(screen.getByTestId('plan-current')).toHaveTextContent('他处保存的新依据');
  });

  it('服务端字段校验失败在表单中提示，用户可以继续修改', async () => {
    server.use(http.post('/api/v1/plans/:id/versions', () => HttpResponse.json(
      errorBody('VALIDATION_ERROR', '数量无效', { fields: [{ field: 'qty', issue: 'lot_rule' }] }), { status: 400 },
    )));
    renderPlan();
    const drawer = await edit();
    fireEvent.click(within(drawer).getByRole('button', { name: '保存为新版本' }));
    expect(await within(drawer).findByText('不符合整手规则')).toBeInTheDocument();
    expect(within(drawer).getByText('有字段未通过校验，请按提示修改。')).toBeInTheDocument();
    fireEvent.change(within(drawer).getByLabelText('数量（股，可空）'), { target: { value: '600' } });
    expect(within(drawer).getByLabelText('数量（股，可空）')).toHaveValue('600');
    fireEvent.click(within(drawer).getByRole('button', { name: '关闭' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('取消关闭不改变计划，再选择已取消并填写备注后计划成为只读', async () => {
    renderPlan();
    fireEvent.click(await screen.findByRole('button', { name: '关闭计划' }));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: '取 消' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByTestId('plan-detail-status')).toHaveTextContent('进行中');
    fireEvent.click(screen.getByRole('button', { name: '关闭计划' }));
    const modal = await screen.findByRole('dialog');
    fireEvent.click(within(modal).getByLabelText('已取消'));
    fireEvent.change(within(modal).getByPlaceholderText('备注（可空，最多 200 字）'), { target: { value: '  暂停研究  ' } });
    fireEvent.click(within(modal).getByRole('button', { name: /确认关闭/ }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(await screen.findByTestId('plan-terminal-note')).toHaveTextContent('计划已取消');
    expect(screen.getByRole('button', { name: '修改计划（新建版本）' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '关闭计划' })).toBeDisabled();
  });

  it('关闭失败保留弹窗和提示，重新确认可完成计划', async () => {
    server.use(http.post('/api/v1/plans/:id/close', () => HttpResponse.json(
      errorBody('INTERNAL_ERROR', '关闭暂时失败'), { status: 500 },
    ), { once: true }));
    renderPlan();
    fireEvent.click(await screen.findByRole('button', { name: '关闭计划' }));
    const modal = await screen.findByRole('dialog');
    fireEvent.click(within(modal).getByRole('button', { name: /确认关闭/ }));
    expect(await within(modal).findByText('关闭暂时失败')).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole('button', { name: /确认关闭/ }));
    expect(await screen.findByTestId('plan-terminal-note')).toHaveTextContent('计划已完成');
  });

  it.each([404, 500])('详情请求失败（%s）显示相应提示', async (status) => {
    server.use(http.get('/api/v1/plans/:id', () => HttpResponse.json(
      errorBody(status === 404 ? 'NOT_FOUND' : 'INTERNAL_ERROR', '读取失败'), { status },
    )));
    renderPlan();
    if (status === 404) {
      expect(await screen.findByText('计划不存在或不属于你。')).toBeInTheDocument();
      fireEvent.click(screen.getByRole('link', { name: '返回计划列表' }));
      expect(await screen.findByRole('heading', { name: '计划列表' })).toBeInTheDocument();
    } else {
      expect(await screen.findByRole('alert')).toHaveTextContent('服务内部错误，请稍后重试');
    }
  });
});
