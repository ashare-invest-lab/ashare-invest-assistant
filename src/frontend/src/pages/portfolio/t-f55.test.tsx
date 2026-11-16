import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import type { ImportRow } from '../../api/accountTypes';
import { errorBody } from '../../mocks/handlerUtils';
import { uid } from '../../mocks/fixtures';
import { server } from '../../mocks/server';
import { computeStats, finding, state } from '../../mocks/session';
import { ImportWizardPage } from './ImportWizardPage';

const ROWS = '/api/v1/imports/:id/rows';

function seed(count = 201) {
  const batch = state.batches[0];
  const template = batch.rows_data[0];
  batch.status = 'previewed';
  batch.committed_at = null;
  batch.file_findings = [];
  batch.rows_data = Array.from({ length: count }, (_, i): ImportRow => ({
    ...template, row_no: i + 1, status: 'ok', findings: [], raw_masked: `掩码示例行 ${i + 1}`,
  }));
  batch.stats = computeStats(batch);
  return batch;
}

function mount(batchId: string) {
  // 直接挂载现有页面，避免其他页面与懒加载初始化影响定向测试。
  const client = makeQueryClient(true);
  const router = createMemoryRouter([
    { path: '/portfolio/import/:batchId', element: <ImportWizardPage /> },
    { path: '/portfolio', element: <div>导入记录</div> },
  ], { initialEntries: [`/portfolio/import/${batchId}`] });
  render(<AppProviders client={client}><RouterProvider router={router} /></AppProviders>);
  return router;
}

describe('T-F55 导入预览服务端分页', () => {
  it.each([
    ['not_a_status', 'not_a_dedup', 'not_a_side'],
    ['__proto__', '__proto__', '__proto__'],
    ['constructor', 'constructor', 'constructor'],
  ])('异常枚举 %s / %s / %s 不崩溃，显示中性未知标签', async (status, dedup_status, side) => {
    const b = seed(1);
    const row = b.rows_data[0];
    server.use(http.get(ROWS, () => HttpResponse.json({
      items: [{ ...row, status, dedup_status, normalized: { ...row.normalized, side } }], next_cursor: null,
    })));
    mount(b.batch_id);
    const table = await screen.findByTestId('rows-table');
    const tags = await within(table).findAllByText('未知');
    expect(tags).toHaveLength(3);
    for (const tag of tags) {
      expect(tag).toHaveClass('ant-tag');
      expect(tag.className).not.toMatch(/ant-tag-(?:has-color|red|green|gold|orange|blue|purple|processing|success|warning|error|default)\b/);
      expect(tag.style.color).toBe('');
      expect(tag.style.backgroundColor).toBe('');
    }
    expect(screen.getByTestId('confirm-panel')).toBeInTheDocument();
    expect(screen.queryByText('Unexpected Application Error!')).not.toBeInTheDocument();
  });

  it('未知及原型键处理选项不崩溃，均显示未知字符串', async () => {
    const b = seed(1);
    const f = finding('IMPORT_UNKNOWN_SECURITY', { row_no: 1, params: { code: '110001.SH' } });
    f.resolution_choices = ['not_a_choice', '__proto__', 'constructor'];
    f.default_resolution = '__proto__';
    b.rows_data[0] = { ...b.rows_data[0], status: 'warning', findings: [f] };
    mount(b.batch_id);
    const item = await screen.findByTestId(`finding-${f.id}`);
    const choices = within(item).getAllByRole('radio');
    expect(choices).toHaveLength(3);
    for (const choice of choices) expect(choice).toHaveAccessibleName(/^未知/);
    expect(within(item).getAllByText('未知')).toHaveLength(3);
    expect(screen.getByTestId('confirm-panel')).toBeInTheDocument();
    expect(screen.queryByText('Unexpected Application Error!')).not.toBeInTheDocument();
  });

  it('200 行之后的警告可加载、逐项处理，已取的预览行保留', async () => {
    const b = seed();
    const f = finding('IMPORT_UNKNOWN_SECURITY', { row_no: 201, params: { code: '110001.SH' } });
    b.rows_data[200] = { ...b.rows_data[200], status: 'warning', findings: [f] };
    b.stats = computeStats(b);
    mount(b.batch_id);
    await screen.findByTestId('import-rows-pager-more');
    expect(screen.getByTestId('rows-table')).toHaveTextContent('掩码示例行 1');
    expect(screen.getByTestId('needs-action')).toHaveTextContent('后续行可能含需处理的警告');
    expect(screen.queryByTestId(`finding-${f.id}`)).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('import-action-rows-pager-more'));
    const item = await screen.findByTestId(`finding-${f.id}`);
    expect(item).toHaveTextContent('第 201 行');
    expect(screen.getByTestId('import-rows-pager-end')).toHaveTextContent('全部 201 行');
    // 默认筛选时，表格与警告检查共用同一份分页缓存。
    expect(screen.getByTestId('rows-table')).toHaveTextContent('掩码示例行 1');
    fireEvent.click(screen.getByTitle('5'));
    expect(screen.getByTestId('rows-table')).toHaveTextContent('掩码示例行 201');
    fireEvent.click(within(item).getByTestId(`resolve-${f.id}`));
    await waitFor(() => expect(screen.getByTestId(`finding-${f.id}`)).toHaveTextContent('已处理：'));
    expect(b.rows_data[200].findings[0].resolution?.choice).toBe(f.default_resolution);
    expect(screen.getByTestId('import-rows-pager-end')).toHaveTextContent('全部 201 行');
  });

  it('后续页使用原样游标；失败保留内容，重试成功后不再显示加载更多', async () => {
    const b = seed();
    const cursors: (string | null)[] = [];
    let failed = false;
    server.use(http.get(ROWS, ({ request }) => {
      const url = new URL(request.url);
      expect(url.searchParams.get('limit')).toBe('200');
      const cursor = url.searchParams.get('cursor');
      cursors.push(cursor);
      if (!cursor) return HttpResponse.json({ items: b.rows_data.slice(0, 200), next_cursor: 'opaque+/=201' });
      if (!failed) {
        failed = true;
        return HttpResponse.json(errorBody('HTTP_ERROR', '预览暂不可用'), { status: 503 });
      }
      return HttpResponse.json({ items: b.rows_data.slice(200), next_cursor: null });
    }));
    mount(b.batch_id);
    fireEvent.click(await screen.findByTestId('import-rows-pager-more'));
    const pager = screen.getByTestId('import-rows-pager');
    expect(await within(pager).findByRole('alert')).toHaveTextContent('下一页加载失败');
    expect(screen.getByTestId('rows-table')).toHaveTextContent('掩码示例行 1');
    fireEvent.click(within(pager).getByRole('button', { name: /重\s*试/ }));
    expect(await screen.findByTestId('import-rows-pager-end')).toHaveTextContent('全部 201 行');
    expect(cursors).toEqual([null, 'opaque+/=201', 'opaque+/=201']);
    expect(screen.queryByTestId('import-rows-pager-more')).not.toBeInTheDocument();
  });

  it('切换筛选不复用旧游标；筛选列表与未筛选警告可分别加载', async () => {
    const b = seed();
    const f = finding('IMPORT_UNKNOWN_SECURITY', { row_no: 201, params: { code: '110001.SH' } });
    b.rows_data[200] = { ...b.rows_data[200], status: 'warning', findings: [f] };
    const requests: URL[] = [];
    server.events.on('request:start', ({ request }) => {
      if (request.url.includes('/rows')) requests.push(new URL(request.url));
    });
    try {
      mount(b.batch_id);
      await screen.findByTestId('import-rows-pager-more');
      fireEvent.mouseDown(within(screen.getByTestId('filter-status')).getByRole('combobox'));
      fireEvent.click(await screen.findByText('警告', { selector: '.ant-select-item-option-content' }));
      expect(await screen.findByTestId('import-rows-pager-end')).toHaveTextContent('全部 1 行');
      expect(screen.getByTestId('rows-table')).toHaveTextContent('掩码示例行 201');
      expect(screen.getByTestId('rows-table')).not.toHaveTextContent('掩码示例行 1');
      expect(requests.filter((u) => u.searchParams.get('status') === 'warning').map((u) => u.searchParams.get('cursor'))).toEqual([null]);
      // 当前筛选只读 warning；独立的未筛选检查仍能取第 201 行并给处理入口。
      expect(screen.queryByTestId(`finding-${f.id}`)).not.toBeInTheDocument();
      fireEvent.click(screen.getByTestId('import-action-rows-pager-more'));
      expect(await screen.findByTestId(`finding-${f.id}`)).toHaveTextContent('第 201 行');
      const last = requests.at(-1)!;
      expect(last.searchParams.get('status')).toBeNull();
      expect(last.searchParams.get('cursor')).toBe('200');
      expect(screen.getByTestId('import-rows-pager-end')).toHaveTextContent('全部 1 行');
    } finally {
      server.events.removeAllListeners('request:start');
    }
  });

  it('空预览显示空态，不显示分页或待处理警告', async () => {
    const b = seed(0);
    mount(b.batch_id);
    const table = await screen.findByTestId('rows-table');
    expect(await within(table).findByText('没有符合条件的行')).toBeInTheDocument();
    expect(screen.queryByTestId('import-rows-pager')).not.toBeInTheDocument();
    expect(screen.queryByTestId('import-rows-pager-end')).not.toBeInTheDocument();
    expect(screen.queryByTestId('needs-action')).not.toBeInTheDocument();
  });

  it('首屏读取失败显示错误，不把失败当作已显示全部', async () => {
    const b = seed();
    server.use(http.get(ROWS, () => HttpResponse.json(errorBody('HTTP_ERROR', '预览读取失败'), { status: 500 })));
    mount(b.batch_id);
    expect((await screen.findAllByText(/服务暂时不可用/)).length).toBeGreaterThan(0);
    expect(screen.queryByTestId('import-rows-pager-end')).not.toBeInTheDocument();
    expect(screen.queryByTestId('import-action-rows-pager-end')).not.toBeInTheDocument();
  });

  it('切换批次从新批次第一页开始，保留每个批次的独立缓存', async () => {
    const b = seed();
    const other = { ...b, batch_id: uid(825), rows_data: [{ ...b.rows_data[0], raw_masked: '另一个批次的掩码行' }] };
    state.batches.push(other);
    const router = mount(b.batch_id);
    fireEvent.click(await screen.findByTestId('import-rows-pager-more'));
    await screen.findByTestId('import-rows-pager-end');
    await act(() => router.navigate(`/portfolio/import/${other.batch_id}`));
    expect(await screen.findByTestId('import-rows-pager-end')).toHaveTextContent('全部 1 行');
    expect(screen.getByTestId('rows-table')).toHaveTextContent('另一个批次的掩码行');
    expect(screen.getByTestId('rows-table')).not.toHaveTextContent('掩码示例行 1');
  });

  it.each(['failed', 'discarded'] as const)('%s 批次不请求预览行，也不显示分页', async (status) => {
    const b = seed();
    b.status = status;
    const readRows = vi.fn();
    server.use(http.get(ROWS, () => { readRows(); return HttpResponse.json({ items: [], next_cursor: null }); }));
    mount(b.batch_id);
    await screen.findByTestId(status === 'failed' ? 'detect-panel' : 'import-discarded');
    expect(readRows).not.toHaveBeenCalled();
    expect(screen.queryByTestId('rows-table')).not.toBeInTheDocument();
    expect(screen.queryByTestId('import-rows-pager')).not.toBeInTheDocument();
  });
});
