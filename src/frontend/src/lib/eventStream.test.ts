import { startEventStream } from './eventStream';

const sseResponse = (init?: RequestInit) => new Response(
  new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(': connected\n\n'));
      init?.signal?.addEventListener('abort', () => controller.error(new DOMException('stopped', 'AbortError')));
    },
  }),
  { headers: { 'Content-Type': 'text/event-stream' } },
);

describe('eventStream polling fallback', () => {
  afterEach(() => vi.useRealTimers());

  it('starts polling only after the third failed connection and keeps SSE backoff running', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, toFake: ['setTimeout', 'clearTimeout'] });
    const polling: boolean[] = [];
    const retryDelays: number[] = [];
    let calls = 0;
    const fetchImpl: typeof fetch = async (_url, init) => {
      calls += 1;
      if (calls <= 3) return new Response(null, { status: 503 });
      return sseResponse(init);
    };

    const stream = startEventStream({
      fetchImpl,
      random: () => 0.5,
      idleTimeoutMs: 120000,
      onMessage: () => undefined,
      onPolling: (enabled) => polling.push(enabled),
      onRetry: ({ delayMs }) => retryDelays.push(delayMs),
    });
    try {
      await vi.advanceTimersByTimeAsync(0);
      expect(calls).toBe(1);
      expect(polling).toEqual([false]);
      expect(retryDelays).toEqual([3000]);

      await vi.advanceTimersByTimeAsync(2999);
      expect(calls).toBe(1);
      expect(polling).toEqual([false]);
      await vi.advanceTimersByTimeAsync(1);
      expect(calls).toBe(2);
      expect(polling).toEqual([false]);
      expect(retryDelays).toEqual([3000, 6000]);

      await vi.advanceTimersByTimeAsync(5999);
      expect(calls).toBe(2);
      expect(polling).toEqual([false]);
      await vi.advanceTimersByTimeAsync(1);
      expect(calls).toBe(3);
      expect(polling).toEqual([false, true]);
      expect(retryDelays).toEqual([3000, 6000, 12000]);
    } finally {
      stream.stop();
    }
  });

  it('stops polling immediately on reconnect and does not re-enable it while connected', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: false, toFake: ['setTimeout', 'clearTimeout'] });
    const polling: boolean[] = [];
    let calls = 0;
    const fetchImpl: typeof fetch = async (_url, init) => {
      calls += 1;
      if (calls <= 3) return new Response(null, { status: 503 });
      return sseResponse(init);
    };

    const stream = startEventStream({
      fetchImpl,
      random: () => 0.5,
      idleTimeoutMs: 120000,
      onMessage: () => undefined,
      onPolling: (enabled) => polling.push(enabled),
    });
    try {
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(3000 + 6000);
      expect(polling).toEqual([false, true]);
      expect(calls).toBe(3);

      await vi.advanceTimersByTimeAsync(11999);
      expect(calls).toBe(3);
      expect(polling).toEqual([false, true]);
      await vi.advanceTimersByTimeAsync(1);
      expect(calls).toBe(4);
      expect(polling).toEqual([false, true, false]);

      await vi.advanceTimersByTimeAsync(60000);
      expect(calls).toBe(4);
      expect(polling).toEqual([false, true, false]);
    } finally {
      stream.stop();
    }
  });
});
