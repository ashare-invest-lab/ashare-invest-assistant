import { QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { expect, it, vi } from 'vitest';

import { makeQueryClient } from '@/app/queryClient';
import { RiskControlsPage } from '@/pages/RiskControlsPage';

it('风控事件首次读取失败后改筛选，仅在新请求成功返回空列表时显示空态', async () => {
  const client = makeQueryClient(true);
  const code = '999901.SH';
  const emptyTitle = '暂无符合条件的风控事件；不是“风险为零”。';
  const filters: { status: string | null; code: string | null }[] = [];
  const pendingResponse = Promise.withResolvers<void>();
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = new URL(String(input), window.location.origin);
    if (url.origin !== window.location.origin || url.pathname !== '/api/v1/risk-controls/events' || init?.method !== 'GET') {
      throw new Error(`风控事件用例收到意外请求：${url.pathname}`);
    }
    const securityCode = url.searchParams.get('security_code');
    filters.push({ status: url.searchParams.get('status'), code: securityCode });
    if (securityCode === code) {
      await pendingResponse.promise;
      return Response.json({ items: [], next_cursor: null });
    }
    return Response.json({
      error: { code: 'INTERNAL_ERROR', message: '示例风控事件读取失败', details: null, request_id: 'rf2' },
    }, { status: 500 });
  });

  try {
    vi.stubGlobal('ResizeObserver', class {
      observe() {}
      unobserve() {}
      disconnect() {}
    });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/risk-controls?tab=events']}>
          <RiskControlsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const panel = within(await screen.findByTestId('risk-events'));
    expect(await panel.findByRole('alert')).toHaveAttribute('data-code', 'INTERNAL_ERROR');
    expect(panel.queryByRole('status', { name: emptyTitle })).not.toBeInTheDocument();

    fireEvent.change(panel.getByRole('textbox', { name: '风控事件证券代码' }), { target: { value: code } });
    await waitFor(() => expect(filters).toEqual([{ status: 'active', code: null }, { status: 'active', code }]));
    expect(panel.getByText('加载中…')).toBeVisible();
    expect(panel.queryByRole('alert')).not.toBeInTheDocument();
    expect(panel.queryByRole('status', { name: emptyTitle })).not.toBeInTheDocument();

    pendingResponse.resolve();
    const empty = await panel.findByRole('status', { name: emptyTitle });
    expect(empty).toBeVisible();
    expect(empty).toHaveTextContent('可调整事件状态、风控类型或证券筛选，查看已有记录。');
    expect(panel.queryByRole('alert')).not.toBeInTheDocument();
    expect(panel.getByRole('button', { name: '加载更多事件' })).toBeDisabled();
  } finally {
    pendingResponse.resolve();
    cleanup();
    client.clear();
    vi.unstubAllGlobals();
  }
});
