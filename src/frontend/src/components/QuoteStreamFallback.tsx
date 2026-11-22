import { useStreamPolling, useStreamStatus } from '../app/streamContext';

const KNOWN_STATUS = {
  connecting: true,
  open: true,
  retrying: true,
  closed: true,
  off: true,
} as const;

const KNOWN_PATH = {
  '/terminal': true,
  '/today': true,
} as const;

export function QuoteStreamFallback({ path }: { path?: keyof typeof KNOWN_PATH }) {
  const status = useStreamStatus() as string;
  const polling = useStreamPolling();
  const disconnected = status === 'retrying' || status === 'closed';
  const known = Object.hasOwn(KNOWN_STATUS, status);
  if (!polling && !disconnected && known) return null;

  const validPath = path !== undefined && Object.hasOwn(KNOWN_PATH, path) ? path : undefined;
  const text = !known ? '未知' : polling
    ? validPath ? `实时推送已断开，已回退 ${validPath} 轮询` : '实时推送已断开'
    : '实时推送已断开，正在重连';
  return <span className="muted small" data-testid="quote-stream-fallback" data-state={status} data-polling={String(polling)}>{text}</span>;
}
