import { act, render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import type { QuoteItem, TerminalResponse, TodayResponse } from '../api/types';
import { useTerminal, useToday } from '../api/queries';
import { StreamPollingContext } from '../app/streamContext';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { startEventStream } from '../lib/eventStream';
import { advance, fakeClock } from '../test/timing';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { StockPage } from './stock/StockPage';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div /> }));

const code = '688001.SH';
const quote = (status: QuoteItem['data_status']): QuoteItem => ({
  security_code: code,
  name: '虚构芯片',
  price: status === 'unavailable' ? null : status === 'fresh' ? '87.10' : '86.90',
  change_pct: status === 'unavailable' ? null : '-1.81',
  volume: status === 'fresh' ? '4520000' : null,
  amount: status === 'fresh' ? '392000.00' : null,
  t: status === 'unavailable' ? null : status === 'fresh' ? '2026-11-02T10:30:00+08:00' : '2026-11-02T15:00:00+08:00',
  data_status: status,
  data_as_of: status === 'unavailable' ? null : status === 'fresh' ? '2026-11-02T10:30:00+08:00' : '2026-11-02T17:05:00+08:00',
  gaps: status === 'unavailable' ? [{ key: 'quotes', reason: 'data_licence_unavailable', message: '虚构证书不可用' }] : [],
});

function renderStock() {
  mockLoginAs('demo_user');
  render(<AppProviders client={makeQueryClient(true)}><MemoryRouter initialEntries={[`/stocks/${code}`]}>
    <Routes><Route path="/stocks/:code" element={<StockPage />} /></Routes>
  </MemoryRouter></AppProviders>);
}

describe('T-T116 / T-F82 stream acceptance', () => {
  it.each(['fresh', 'stale', 'unavailable'] as const)('个股页展示服务端 %s 三态', async (status) => {
    const body = quote(status);
    server.use(http.get('/api/v1/quotes', () => HttpResponse.json({ items: [body] })));
    renderStock();

    const head = await screen.findByTestId('stock-head');
    await waitFor(() => expect(head.querySelector('.q-price')).toBeTruthy());
    expect(head).toHaveTextContent(status === 'fresh' ? '最新' : status === 'stale' ? '已过期' : '不可用');
    expect(head).toHaveTextContent(status === 'fresh' ? '87.10' : status === 'stale' ? '86.90' : '—');
    if (status === 'stale') expect(screen.getByTestId('quote-stale-tag')).toHaveTextContent('收盘价·11-02');
    if (status === 'unavailable') expect(head).not.toHaveTextContent('86.90');
  });

  it('个股行情在 SSE 未发布 quote 时按 15 秒 GET /quotes 回退轮询', async () => {
    fakeClock();
    let calls = 0;
    server.use(http.get('/api/v1/quotes', () => {
      calls += 1;
      return HttpResponse.json({ items: [quote('fresh')] });
    }));
    renderStock();
    await waitFor(() => expect(calls).toBe(1));
    // shouldAdvanceTime 会吃掉 waitFor 的真实耗时，14_999 会跨过 15s；留 1s 余量仍断言未提前轮询。
    await advance(14_000);
    expect(calls).toBe(1);
    await advance(1_000);
    await waitFor(() => expect(calls).toBe(2));
  });

  function FallbackProbe() {
    const terminal = useTerminal('all');
    const today = useToday();
    return <div data-testid="fallback-probe" data-terminal={terminal.data?.trade_date ?? ''} data-today={today.data?.trade_date ?? ''} />;
  }

  it('SSE 未接通时 /terminal 与 /today 均以至少 15 秒并带 If-None-Match 轮询', async () => {
    fakeClock();
    const seen: Record<string, (string | null)[]> = { terminal: [], today: [] };
    const terminalBody = { account_id: null, server_time: '2026-11-02T10:31:00+08:00', trade_date: '2026-11-02', session: 'morning', account: null, rows: [], truncated: false, unread_notifications: 0 } satisfies TerminalResponse;
    const todayBody = { account_id: null, server_time: '2026-11-02T10:31:00+08:00', trade_date: '2026-11-02', session: 'morning', market: { regime: null, regime_position_range: null, data_status: 'unavailable' }, focus: { items: [], more: false }, pending_plan_drafts: { items: [], more: false }, released_reasons: { items: [], more: false }, risk_flags: { items: [], more: false }, invalidations_today: { items: [], more: false }, daily_report: { date: '2026-11-02', status: 'not_yet' }, reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 }, unread_notifications: 0, alerts: { items: [], more: false }, plan_triggers: { items: [], more: false }, data_gaps: { items: [], more: false }, evidence: [] } satisfies TodayResponse;
    const endpoints = [{ path: 'terminal', body: terminalBody, key: 'terminal' }, { path: 'today', body: todayBody, key: 'today' }] as const;
    for (const endpoint of endpoints) {
      server.use(http.get(`/api/v1/${endpoint.path}`, ({ request }) => {
        seen[endpoint.key].push(request.headers.get('If-None-Match'));
        const etag = `W/"${endpoint.key}"`;
        return request.headers.get('If-None-Match') === etag ? new HttpResponse(null, { status: 304, headers: { ETag: etag } }) : HttpResponse.json(endpoint.body, { headers: { ETag: etag } });
      }));
    }
    const client = makeQueryClient(true);
    render(<QueryClientProvider client={client}><StreamPollingContext.Provider value={true}><FallbackProbe /></StreamPollingContext.Provider></QueryClientProvider>);
    await waitFor(() => expect(seen.terminal).toHaveLength(1));
    await waitFor(() => expect(seen.today).toHaveLength(1));
    // shouldAdvanceTime 会吃掉 waitFor 的真实耗时，14_999 会跨过 15s；留 1s 余量仍断言未提前轮询。
    await advance(14_000);
    expect(seen.terminal).toHaveLength(1);
    expect(seen.today).toHaveLength(1);
    await advance(1_000);
    await waitFor(() => expect(seen.terminal).toHaveLength(2));
    await waitFor(() => expect(seen.today).toHaveLength(2));
    expect(seen.terminal[1]).toBe('W/"terminal"');
    expect(seen.today[1]).toBe('W/"today"');
  });

  it('startEventStream 断线按 Last-Event-ID 续传并重连', async () => {
    fakeClock(false);
    const requests: HeadersInit[] = [];
    const received: string[] = [];
    let connection = 0;
    const fetchImpl: typeof fetch = vi.fn(async (_url, init) => {
      requests.push(init?.headers ?? {});
      connection += 1;
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          if (connection === 1) {
            controller.enqueue(new TextEncoder().encode('id: 7\nevent: quote\ndata: {"t":"2026-11-02T10:30:00+08:00"}\n\n'));
            controller.close();
          }
        },
      });
      return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } });
    });
    const handle = startEventStream({ retryMs: 10, maxRetryMs: 10, idleTimeoutMs: 1000, random: () => 0.5, fetchImpl, onMessage: (m) => received.push(`${m.id}:${m.event}`) });
    await act(async () => { await Promise.resolve(); });
    await waitFor(() => expect(received).toContain('7:quote'));
    await advance(10);
    await waitFor(() => expect(connection).toBe(2));
    expect(new Headers(requests[1]).get('Last-Event-ID')).toBe('7');
    handle.stop();
  });

  it('startEventStream 无心跳达到超时后重连', async () => {
    fakeClock(false);
    let connections = 0;
    const fetchImpl: typeof fetch = vi.fn(async (_url, init) => {
      connections += 1;
      const signal = init?.signal;
      return new Response(new ReadableStream<Uint8Array>({
        start(controller) {
          signal?.addEventListener('abort', () => {
            try { controller.error(signal.reason ?? new DOMException('heartbeat timeout', 'TimeoutError')); } catch { /* already closed */ }
          });
        },
      }), { headers: { 'Content-Type': 'text/event-stream' } });
    });
    const handle = startEventStream({ retryMs: 0, maxRetryMs: 0, idleTimeoutMs: 15, random: () => 0.5, fetchImpl, onMessage: () => undefined });
    await act(async () => { await Promise.resolve(); });
    await waitFor(() => expect(connections).toBe(1));
    await advance(15);
    await waitFor(() => expect(connections).toBe(2));
    handle.stop();
  });
});
