import { act, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { StreamProvider } from '../app/StreamProvider';
import { QuoteStreamFallback } from '../components/QuoteStreamFallback';
import { StreamPollingContext, StreamStatusContext, isStreamEnabled, streamConfig, useStreamStatus } from '../app/streamContext';
import { applyStreamEvent } from '../app/streamEvents';
import { mk, useQuote } from '../api/marketQueries';
import type { QuoteItem, TerminalResponse } from '../api/types';
import { makeQueryClient } from '../app/queryClient';
import { STALE_QUOTE_EXAMPLE, TERMINAL_ROWS } from '../mocks/fixtures';
import { mockLoginAs } from '../mocks/session';
import { server } from '../mocks/server';
import { pushStreamEvent, streamConnectionCount } from '../mocks/streamHandlers';
import { StockPage } from './stock/StockPage';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div /> }));

beforeEach(() => mockLoginAs('demo_user'));
afterEach(() => Object.assign(streamConfig, { enabled: false, retryMs: undefined, maxRetryMs: undefined, idleTimeoutMs: undefined }));

const quoteEvent = (code: string) => ({
  id: '1', type: 'quote' as const,
  data: { items: [{ security_code: code, name: '演示证券', price: '12.34', change_pct: '1.20', amount: '5678', t: '2026-11-02T10:41:00+08:00' }], data_as_of: '2026-11-02T10:41:01+08:00' },
});

describe('T-F82 stream consumption', () => {
  it('only test mode disables the stream', () => {
    expect(isStreamEnabled('test')).toBe(false);
    expect(isStreamEnabled('development')).toBe(true);
    expect(isStreamEnabled('production')).toBe(true);
  });

  it('updates terminal and an existing quote cache without changing data status', () => {
    const qc = new QueryClient();
    const row = TERMINAL_ROWS.find((item) => item.quote)!;
    const before = { ...row, quote: { ...row.quote! }, data_status: row.data_status };
    qc.setQueryData<TerminalResponse>(['terminal', 'all'], { rows: [before] } as unknown as TerminalResponse);
    qc.setQueryData(['quotes', row.security_code], { ...row.quote, data_status: 'stale', data_as_of: 'old' });
    applyStreamEvent(qc, quoteEvent(row.security_code));

    const terminal = qc.getQueryData<TerminalResponse>(['terminal', 'all'])!.rows[0];
    const quote = qc.getQueryData<Record<string, unknown>>(['quotes', row.security_code])!;
    expect(terminal.quote).toMatchObject({ price: '12.34', change_pct: '1.20', amount: '5678', t: '2026-11-02T10:41:00+08:00' });
    expect(terminal.data_status).toBe(before.data_status);
    expect(quote).toMatchObject({ price: '12.34', change_pct: '1.20', amount: '5678', t: '2026-11-02T10:41:00+08:00', data_as_of: '2026-11-02T10:41:01+08:00', data_status: 'stale' });
    expect(quote).not.toHaveProperty('source');
    expect(quote).not.toHaveProperty('basis');
    expect(qc.getQueryData(['quotes', '999999.SZ'])).toBeUndefined();
  });

  it('ignores inherited and unknown quote fields', () => {
    const qc = new QueryClient();
    const row = TERMINAL_ROWS.find((item) => item.quote)!;
    const invalid = Object.create({ security_code: row.security_code, price: '99.99' });
    applyStreamEvent(qc, { id: '2', type: 'quote', data: { items: [invalid], data_as_of: 'ignored' } } as never);
    expect(qc.getQueryData(['terminal'])).toBeUndefined();
  });

  it('delivers an opened stream quote to terminal and mounted /quotes cache', async () => {
    const qc = new QueryClient();
    const row = TERMINAL_ROWS.find((item) => item.quote)!;
    qc.setQueryData<TerminalResponse>(['terminal', 'all'], { rows: [row] } as unknown as TerminalResponse);
    Object.assign(streamConfig, { enabled: true, retryMs: 20, maxRetryMs: 80, idleTimeoutMs: 2_000 });

    function Consumer() {
      const quote = useQuote(row.security_code);
      const status = useStreamStatus();
      return <div data-testid="stream-state" data-state={status}>{quote.data?.price ?? 'loading'}</div>;
    }

    render(<AppProviders client={qc}><StreamProvider><Consumer /></StreamProvider></AppProviders>);
    await waitFor(() => expect(screen.getByTestId('stream-state')).toHaveAttribute('data-state', 'open'));
    await waitFor(() => expect(streamConnectionCount()).toBe(1));
    act(() => void pushStreamEvent('quote', quoteEvent(row.security_code).data));
    await waitFor(() => expect(screen.getByTestId('stream-state')).toHaveTextContent('12.34'));
    expect(qc.getQueryData<TerminalResponse>(['terminal', 'all'])!.rows[0].quote).toMatchObject({ price: '12.34', amount: '5678' });
    expect(qc.getQueryData<Record<string, unknown>>(['quotes', row.security_code])).not.toHaveProperty('source');
    expect(qc.getQueryData<Record<string, unknown>>(['quotes', row.security_code])).not.toHaveProperty('basis');
  });

  it('useQuote 固定每 15 秒轮询，与推送状态无关', () => {
    for (const polling of [false, true]) {
      const qc = new QueryClient();
      const view = renderHook(() => useQuote('600000.SH'), {
        wrapper: ({ children }) => <StreamPollingContext.Provider value={polling}><QueryClientProvider client={qc}>{children}</QueryClientProvider></StreamPollingContext.Provider>,
      });
      expect(qc.getQueryCache().find({ queryKey: mk.quote('600000.SH') })!.observers[0].options.refetchInterval).toBe(15_000);
      view.unmount();
    }
  });
});

describe('T-F82 fallback status', () => {
  function renderFallback(status: string, polling: boolean, path?: '/terminal' | '/today') {
    return render(
      <StreamStatusContext.Provider value={status as never}>
        <StreamPollingContext.Provider value={polling}><QuoteStreamFallback {...(path ? { path } : {})} /></StreamPollingContext.Provider>
      </StreamStatusContext.Provider>,
    );
  }

  it.each(['/terminal', '/today'] as const)('显示 %s 回退轮询和状态属性', (path) => {
    renderFallback('closed', true, path);
    expect(screen.getByTestId('quote-stream-fallback')).toHaveTextContent(`实时推送已断开，已回退 ${path} 轮询`);
    expect(screen.getByTestId('quote-stream-fallback')).toHaveAttribute('data-state', 'closed');
    expect(screen.getByTestId('quote-stream-fallback')).toHaveAttribute('data-polling', 'true');
  });

  it('个股页省略 path 时不显示 /quotes 来源', () => {
    renderFallback('closed', true);
    expect(screen.getByTestId('quote-stream-fallback')).toHaveTextContent('实时推送已断开');
    expect(screen.getByTestId('quote-stream-fallback')).not.toHaveTextContent('/quotes');
  });

  it('仅重连且尚未轮询时显示重连文案', () => {
    renderFallback('retrying', false, '/terminal');
    expect(screen.getByTestId('quote-stream-fallback')).toHaveTextContent('实时推送已断开，正在重连');
  });

  it('未启用推送且轮询开启时不显示断线提示', () => {
    renderFallback('off', true, '/terminal');
    expect(screen.queryByTestId('quote-stream-fallback')).not.toBeInTheDocument();
  });

  it.each(['unknown', '__proto__', 'constructor'])('状态 %s 显示未知', (status) => {
    renderFallback(status, true, '/terminal');
    expect(screen.getByTestId('quote-stream-fallback')).toHaveTextContent('未知');
  });

  it.each(['__proto__', 'constructor'])('path %s 不当成合法回退路径', (path) => {
    renderFallback('closed', true, path as '/terminal');
    expect(screen.getByTestId('quote-stream-fallback')).toHaveTextContent('实时推送已断开');
    expect(screen.getByTestId('quote-stream-fallback')).not.toHaveTextContent('轮询');
  });
});

function renderStockQuote(item: QuoteItem) {
  server.use(http.get('/api/v1/quotes', () => HttpResponse.json({ items: [item] })));
  render(<AppProviders client={makeQueryClient(true)}><MemoryRouter initialEntries={['/stocks/688001.SH']}>
    <Routes><Route path="/stocks/:code" element={<StockPage />} /></Routes>
  </MemoryRouter></AppProviders>);
}

function quoteWithExtraFields(overrides: Partial<QuoteItem>): QuoteItem {
  const quote: Record<string, unknown> = { ...STALE_QUOTE_EXAMPLE.item, ...overrides };
  for (const key of ['source', 'basis', '__proto__', 'constructor', 'unknown', 'close']) {
    Object.defineProperty(quote, key, { value: '示例来源字段', enumerable: true, configurable: true });
  }
  return quote as unknown as QuoteItem;
}

describe('T-F82 行情展示口径', () => {
  it('fresh 且有 t 时不显示收盘价标签，行上的来源字段不参与展示', async () => {
    renderStockQuote(quoteWithExtraFields({ data_status: 'fresh', t: '2026-11-02T10:41:00+08:00', data_as_of: '2026-11-02T10:41:01+08:00' }));
    const head = await screen.findByTestId('stock-head');
    expect(within(head).queryByTestId('quote-stale-tag')).not.toBeInTheDocument();
    expect(head).not.toHaveTextContent('示例来源字段');
    expect(head).not.toHaveTextContent('source');
    expect(head).not.toHaveTextContent('basis');
  });

  it('stale 且有 t 时显示收盘价标签', async () => {
    renderStockQuote(quoteWithExtraFields({ data_status: 'stale', t: '2026-10-30T15:00:00+08:00', data_as_of: '2026-11-02T08:20:00+08:00' }));
    expect(await screen.findByTestId('quote-stale-tag')).toHaveTextContent('收盘价·10-30');
  });

  it('unavailable 不展示旧价', async () => {
    renderStockQuote(quoteWithExtraFields({ data_status: 'unavailable', price: '86.90', change_pct: '-1.81', t: '2026-10-30T15:00:00+08:00', data_as_of: null,
      gaps: [{ key: 'quotes', reason: 'data_licence_unavailable', message: '本人数据证书不可用' }] }));
    const head = await screen.findByTestId('stock-head');
    await waitFor(() => expect(head.querySelector('.q-price')).not.toBeNull());
    expect(head.querySelector('.q-price')).toHaveTextContent('—');
    expect(head).not.toHaveTextContent('86.90');
    expect(head).not.toHaveTextContent('-1.81%');
    expect(within(head).queryByTestId('quote-stale-tag')).not.toBeInTheDocument();
  });
});
