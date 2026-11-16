/** T-F56：导入历史使用契约 §1.2 / §7.2 游标分页；所有请求由现有 MSW 拦截。 */
import { configure, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import type { ImportBatchSummary } from '../../api/accountTypes';
import { ACCOUNT_ID, uid } from '../../mocks/fixtures';
import { errorBody, page } from '../../mocks/handlerUtils';
import { server } from '../../mocks/server';
import { SECOND_ACCOUNT_ID, state } from '../../mocks/session';
import { preloadRoutes } from '../../test/preloadRoutes';
import { settled } from '../../test/timing';

configure({ asyncUtilTimeout: 5000 });
beforeAll(() => preloadRoutes(routes), 30_000);

function renderHistory() {
  const client = makeQueryClient(true);
  const router = createMemoryRouter(routes, { initialEntries: [`/portfolio?tab=imports&account_id=${ACCOUNT_ID}`] });
  render(<AppProviders client={client}><RouterProvider router={router} /></AppProviders>);
  return { client, router };
}

function seedBatches(n = 51) {
  const base = state.batches[0];
  state.batches = Array.from({ length: n }, (_, i) => ({ ...base, batch_id: uid(5600 + i), idem: new Map() }));
  return state.batches;
}

function batchRow(batchId: string) {
  return screen.getByTestId('imports-tab').querySelector(`tr[data-row-key="${batchId}"]`);
}

describe('T-F56 导入历史分页', () => {
  it.each(['not_a_status', '__proto__', 'constructor', 'toString'].flatMap((status) =>
    [false, true].map((nextPage) => ({ status, nextPage })),
  ))('异常状态 $status（后续页：$nextPage）显示中性的「未知」，保留列表且无空白标签', async ({ status, nextPage }) => {
    const batches = seedBatches(nextPage ? 51 : 1);
    const target = batches[batches.length - 1];
    server.use(http.get('/api/v1/imports', ({ request }) => {
      const result = page(batches, new URL(request.url));
      return HttpResponse.json({
        ...result,
        items: result.items.map((batch) => batch.batch_id === target.batch_id ? { ...batch, status } : batch),
      });
    }));
    renderHistory();
    if (nextPage) fireEvent.click(await screen.findByTestId('imports-pager-more'));
    expect(await screen.findByTestId('imports-pager-end')).toHaveTextContent(`已显示全部 ${batches.length} 条`);
    const row = batchRow(target.batch_id) as HTMLElement;
    expect(row).toBeInTheDocument();
    const tag = within(row).getByText('未知');
    expect(tag).toHaveClass('ant-tag');
    expect(tag.className).not.toMatch(/ant-tag-(?:has-color|default|processing|blue|green|red|purple)\b/);
    expect(tag).not.toHaveAttribute('color');
    expect(tag.style.color).toBe('');
    expect(tag.style.backgroundColor).toBe('');
    expect(screen.getByTestId('imports-tab').querySelectorAll('tr[data-row-key]')).toHaveLength(batches.length);
    for (const label of screen.getByTestId('imports-tab').querySelectorAll('.ant-tag')) {
      expect(label.textContent?.trim()).not.toBe('');
    }
    expect(screen.queryByText('Unexpected Application Error!')).toBeNull();
  });

  it('默认 50 条，加载第 51 条后到底，后续批次仍可查看', async () => {
    const batches = seedBatches();
    const calls: URL[] = [];
    // 只记录请求，响应沿用现有 /imports handler（内部使用 page()）。
    server.use(http.get('/api/v1/imports', ({ request }) => { calls.push(new URL(request.url)); }));
    const { client, router } = renderHistory();
    expect(await screen.findByTestId('imports-pager')).toHaveTextContent('已加载 50 条');
    expect(batchRow(batches[49].batch_id)).toBeInTheDocument();
    expect(batchRow(batches[50].batch_id)).toBeNull();
    fireEvent.click(screen.getByTestId('imports-pager-more'));
    expect(await screen.findByTestId('imports-pager-end')).toHaveTextContent('已显示全部 51 条');
    expect(batchRow(batches[0].batch_id)).toBeInTheDocument();
    expect(batchRow(batches[50].batch_id)).toBeInTheDocument();
    expect(screen.queryByTestId('imports-pager-more')).toBeNull();
    await settled(client);
    expect(calls.map((u) => [u.searchParams.get('account_id'), u.searchParams.get('limit'), u.searchParams.get('cursor')]))
      .toEqual([[ACCOUNT_ID, '50', null], [ACCOUNT_ID, '50', '50']]);
    fireEvent.click(within(batchRow(batches[50].batch_id) as HTMLElement).getByRole('button', { name: /查\s*看/ }));
    await waitFor(() => expect(router.state.location.pathname).toBe(`/portfolio/import/${batches[50].batch_id}`));
    expect(await screen.findByTestId('import-batch')).toBeInTheDocument();
  });

  it('不透明游标原样传递，跨页按 batch_id 去重并保留首次内容', async () => {
    const batches = seedBatches();
    const cursor = 'opaque+/= %&?中文';
    const seen: (string | null)[] = [];
    server.use(http.get('/api/v1/imports', ({ request }) => {
      const url = new URL(request.url);
      const token = url.searchParams.get('cursor');
      seen.push(token);
      if (token === null) return HttpResponse.json({ ...page(batches, url), next_cursor: cursor });
      if (token !== cursor) return HttpResponse.json(errorBody('INVALID_CURSOR', '游标被修改'), { status: 400 });
      const duplicate: ImportBatchSummary = { ...batches[49], kind: 'positions' };
      return HttpResponse.json({ items: [duplicate, batches[50]], next_cursor: null });
    }));
    renderHistory();
    fireEvent.click(await screen.findByTestId('imports-pager-more'));
    expect(await screen.findByTestId('imports-pager-end')).toHaveTextContent('已显示全部 51 条');
    expect(screen.getByTestId('imports-tab').querySelectorAll('tr[data-row-key]')).toHaveLength(51);
    expect(batchRow(batches[49].batch_id)).toHaveTextContent('交割单 / 成交');
    expect(batchRow(batches[50].batch_id)).toBeInTheDocument();
    expect(seen).toEqual([null, cursor]);
  });

  it('下一页失败保留已加载内容，重试复用游标并成功追加', async () => {
    const batches = seedBatches();
    const seen: (string | null)[] = [];
    let failNext = true;
    server.use(http.get('/api/v1/imports', ({ request }) => {
      const url = new URL(request.url);
      const cursor = url.searchParams.get('cursor');
      seen.push(cursor);
      if (cursor && failNext) return HttpResponse.json(errorBody('SERVICE_UNAVAILABLE', '稍后重试'), { status: 503 });
      return HttpResponse.json(page(batches, url));
    }));
    renderHistory();
    fireEvent.click(await screen.findByTestId('imports-pager-more'));
    expect(await screen.findByText('下一页加载失败，已加载的内容保留')).toBeInTheDocument();
    expect(batchRow(batches[0].batch_id)).toBeInTheDocument();
    expect(batchRow(batches[49].batch_id)).toBeInTheDocument();
    expect(batchRow(batches[50].batch_id)).toBeNull();
    expect(screen.getByTestId('imports-tab')).not.toHaveTextContent('暂无导入记录');
    failNext = false;
    fireEvent.click(within(screen.getByTestId('imports-pager')).getByRole('button', { name: /重\s*试/ }));
    expect(await screen.findByTestId('imports-pager-end')).toHaveTextContent('已显示全部 51 条');
    expect(batchRow(batches[50].batch_id)).toBeInTheDocument();
    expect(screen.queryByText('下一页加载失败，已加载的内容保留')).toBeNull();
    expect(seen).toEqual([null, '50', '50']);
  });

  it('空列表保留原有空态，不显示分页条', async () => {
    state.batches = [];
    const { client } = renderHistory();
    await screen.findByTestId('imports-tab');
    await settled(client);
    expect(screen.getByText('暂无导入记录')).toBeInTheDocument();
    expect(screen.queryByTestId('imports-pager')).toBeNull();
    expect(screen.queryByTestId('imports-pager-end')).toBeNull();
  });

  it('首屏失败保留原有 ErrorBox，不显示下一页重试', async () => {
    server.use(http.get('/api/v1/imports', () => HttpResponse.json(errorBody('SERVICE_UNAVAILABLE', '历史加载失败'), { status: 503 })));
    const { client } = renderHistory();
    await screen.findByTestId('imports-tab');
    await settled(client);
    expect(screen.getByTestId('imports-tab')).toHaveTextContent('加载失败');
    expect(screen.queryByTestId('imports-pager')).toBeNull();
    expect(screen.queryByText('下一页加载失败，已加载的内容保留')).toBeNull();
  });

  it('切换账户后从首屏开始，不混入另一账户已加载的后续页', async () => {
    const batches = seedBatches();
    state.batches.push({ ...batches[0], batch_id: uid(5700), account_id: SECOND_ACCOUNT_ID, idem: new Map() });
    const calls: URL[] = [];
    server.use(http.get('/api/v1/imports', ({ request }) => { calls.push(new URL(request.url)); }));
    const { router, client } = renderHistory();
    fireEvent.click(await screen.findByTestId('imports-pager-more'));
    await screen.findByTestId('imports-pager-end');
    fireEvent.mouseDown(screen.getByTestId('account-select').querySelector('.ant-select-selector') ?? screen.getByTestId('account-select'));
    fireEvent.click(await screen.findByText(/备用账户.*演示证券/));
    await waitFor(() => expect(router.state.location.search).toContain(SECOND_ACCOUNT_ID));
    await waitFor(() => expect(batchRow(uid(5700))).toBeInTheDocument());
    expect(screen.getByTestId('imports-pager-end')).toHaveTextContent('已显示全部 1 条');
    expect(batchRow(batches[50].batch_id)).toBeNull();
    await settled(client);
    expect(calls.filter((u) => u.searchParams.get('account_id') === SECOND_ACCOUNT_ID).map((u) => u.searchParams.get('cursor'))).toEqual([null]);
  });
});
