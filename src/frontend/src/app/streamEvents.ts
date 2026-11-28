import { apiGet } from '../api/client';
import { nk, readUnreadNotifications } from '../api/notificationQueries';
import { isNotificationInput, latestNotifications, projectNotification, notificationVersion, rememberNotificationVersions } from '../lib/notifications';
/**
 * 把 §8 SSE 事件落到 TanStack Query 缓存（T-F14）。原则：
 * - 能直接就地更新的（quote 的行情、suggestion 的摘要）先就地改，避免整页重拉；
 * - 其余一律按查询键前缀失效，由各页面按需重拉（失效不会请求没有挂载的查询）；
 * - 未知事件类型忽略（契约后续加事件时前端不报错）；data 不是合法 JSON 的事件丢弃。
 */
import type { InfiniteData, QueryClient, QueryKey } from '@tanstack/react-query';
import type { DataStatus } from '../api/enums';
import type { Notification, Paged, QuoteItem, TerminalResponse, TodayResponse } from '../api/types';
import { isStreamEventType, type StreamEventMap, type StreamEventType } from '../api/streamTypes';
import type { SseMessage } from '../lib/sseParser';
import { isQuoteStale } from '../lib/quoteDisplay';

export interface ParsedStreamEvent<K extends StreamEventType = StreamEventType> { id: string | null; type: K; data: StreamEventMap[K] }

export function parseStreamMessage(m: SseMessage): ParsedStreamEvent | null {
  if (!isStreamEventType(m.event)) return null;
  try {
    const raw: unknown = JSON.parse(m.data);
    if (m.event === 'reset') {
      if (!raw || typeof raw !== 'object') return null; const reset = raw as Record<string, unknown>;
      if (!['expired', 'unknown'].includes(String(reset.reason)) || !(reset.latest_event_id === null || typeof reset.latest_event_id === 'string' && /^\d+$/.test(reset.latest_event_id))) return null;
    }
    if (m.event === 'notification' && !isNotificationInput(raw)) return null;
    const data = m.event === 'notification' && isNotificationInput(raw) ? projectNotification(raw) : raw;
    return { id: m.id, type: m.event, data: data as StreamEventMap[StreamEventType] };
  } catch {
    return null;
  }
}

const inv = (qc: QueryClient, ...keys: QueryKey[]) => {
  for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
};

/** 首页与终端都是聚合视图：多数业务事件都会让它们变化（ETag 未变时服务端回 304，代价很小） */
const AGGREGATES: QueryKey[] = [['terminal'], ['today']];

const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const own = (value: Record<string, unknown>, key: string) => Object.hasOwn(value, key);

type QuotePatch = Partial<{ name: string; price: string; change_pct: string; amount: string; t: string }>;
type QuoteUpdate = { code: string; patch: QuotePatch };

function quotePatch(value: unknown): QuoteUpdate | null {
  if (!isRecord(value) || !own(value, 'security_code') || typeof value.security_code !== 'string' || value.security_code === '') return null;
  const patch: Partial<{ name: string; price: string; change_pct: string; amount: string; t: string }> = {};
  for (const key of ['name', 'price', 'change_pct', 'amount', 't'] as const) {
    if (!own(value, key) || typeof value[key] !== 'string') return null;
    patch[key] = value[key] as string;
  }
  return { code: value.security_code, patch };
}

function quoteTime(t: string | null | undefined): number | null {
  if (!t) return null;
  const parsed = Date.parse(t);
  return Number.isFinite(parsed) ? parsed : null;
}

/** SSE 可以重放旧帧。项级 t 倒退时保留缓存中的较新行情。 */
function isAtLeastAsNew(incoming: string | undefined, current: string | null | undefined): boolean {
  if (!current) return true;
  const nextAt = quoteTime(incoming);
  const currentAt = quoteTime(current);
  if (nextAt !== null && currentAt !== null) return nextAt >= currentAt;
  return typeof incoming === 'string' && incoming >= current;
}

function freshnessOf(snapshot: Pick<TerminalResponse, 'server_time' | 'session' | 'trade_date'> | Pick<TodayResponse, 'server_time' | 'session' | 'trade_date'>) {
  return { now: snapshot.server_time, session: snapshot.session, tradeDate: snapshot.trade_date };
}

function staleStatus(status: DataStatus, t: string, snapshot: Pick<TerminalResponse, 'server_time' | 'session' | 'trade_date'> | Pick<TodayResponse, 'server_time' | 'session' | 'trade_date'>): DataStatus {
  if (typeof snapshot.server_time !== 'string') return status;
  return status === 'fresh' && isQuoteStale(t, freshnessOf(snapshot)) ? 'stale' : status;
}

function firstTerminalSnapshot(qc: QueryClient): TerminalResponse | undefined {
  return qc.getQueriesData<TerminalResponse>({ queryKey: ['terminal'] }).map(([, data]) => data).find((data): data is TerminalResponse => !!data && typeof data.server_time === 'string');
}

export function applyStreamEvent(qc: QueryClient, e: ParsedStreamEvent) {
  switch (e.type) {
    case 'heartbeat':
      return;
    case 'quote': {
      const d = e.data as unknown;
      if (!isRecord(d) || !own(d, 'items') || !Array.isArray(d.items) || !own(d, 'data_as_of') || typeof d.data_as_of !== 'string') return;
      const updates = d.items.map(quotePatch).filter((q): q is QuoteUpdate => q !== null);
      const byCode = new Map<string, QuotePatch>();
      for (const update of updates) {
        const previous = byCode.get(update.code);
        if (!previous || isAtLeastAsNew(update.patch.t, previous.t)) byCode.set(update.code, update.patch);
      }
      qc.setQueriesData<TerminalResponse>({ queryKey: ['terminal'] }, (old) => {
        if (!old) return old;
        let changed = false;
        const rows = old.rows.map((r) => {
          const patch = byCode.get(r.security_code);
          if (!patch) return r;
          if (!isAtLeastAsNew(patch.t, r.quote?.t)) return r;
          const terminalPatch = { price: patch.price!, change_pct: patch.change_pct!, amount: patch.amount!, t: patch.t! };
          const next = r.quote ? { ...r.quote, ...terminalPatch } : {
            price: terminalPatch.price, change_pct: terminalPatch.change_pct, amount: terminalPatch.amount, t: terminalPatch.t,
          };
          const nextStatus = staleStatus(r.data_status, terminalPatch.t, old);
          if (r.quote && Object.entries(terminalPatch).every(([key, value]) => r.quote?.[key as keyof typeof r.quote] === value) && nextStatus === r.data_status) return r;
          changed = true;
          return { ...r, quote: next, data_status: nextStatus };
        });
        return changed ? { ...old, rows } : old;
      });
      qc.setQueryData<TodayResponse>(['today'], (old) => {
        if (!old) return old;
        let changed = false;
        const items = old.focus.items.map((r) => {
          const patch = byCode.get(r.security_code);
          if (!patch || !isAtLeastAsNew(patch.t, r.quote?.t)) return r;
          const nextQuote = r.quote ? { ...r.quote, price: patch.price!, change_pct: patch.change_pct!, amount: patch.amount!, t: patch.t! } : {
            price: patch.price!, change_pct: patch.change_pct!, amount: patch.amount!, t: patch.t!,
          };
          const nextStatus = staleStatus(r.data_status, patch.t!, old);
          if (r.quote && Object.entries(nextQuote).every(([key, value]) => r.quote?.[key as keyof typeof r.quote] === value) && nextStatus === r.data_status) return r;
          changed = true;
          return { ...r, quote: nextQuote, data_status: nextStatus };
        });
        return changed ? { ...old, focus: { ...old.focus, items } } : old;
      });
      for (const [code, patch] of byCode) {
        const key = ['quotes', code] as const;
        if (!qc.getQueryData(key)) continue;
        qc.setQueryData<QuoteItem>(key, (old) => {
          if (!old) return old;
          if (!isAtLeastAsNew(patch.t, old.t)) return old;
          const next = { ...old, ...patch };
          next.data_as_of = d.data_as_of as string;
          const snapshot = firstTerminalSnapshot(qc);
          if (snapshot) next.data_status = staleStatus(next.data_status, patch.t!, snapshot);
          else if (next.data_status === 'fresh' && isQuoteStale(patch.t!)) next.data_status = 'stale';
          return next;
        });
      }
      return;
    }
    case 'suggestion': {
      const d = e.data as StreamEventMap['suggestion'];
      qc.setQueriesData<TerminalResponse>({ queryKey: ['terminal'] }, (old) => {
        if (!old) return old;
        if (!old.rows.some((r) => r.security_code === d.security_code)) return old;
        return { ...old, rows: old.rows.map((r) => (r.security_code === d.security_code ? { ...r, suggestion: d.summary } : r)) };
      });
      // 被取代的旧卡状态变了（status / superseded_by_id）
      inv(qc, ['suggestions'], ['today'], ...(d.supersedes_id ? [['suggestion', d.supersedes_id]] : []));
      return;
    }
    case 'signal':
      inv(qc, ['signals']);
      return;
    case 'candidate_signal': {
      const d = e.data as StreamEventMap['candidate_signal'];
      inv(qc, ['candidate-signals'], ['candidate-signal', d.id], ...AGGREGATES);
      return;
    }
    case 'reason_released':
      inv(qc, ['non-executable-reasons'], ['candidate-signals'], ['candidate-signal', (e.data as StreamEventMap['reason_released']).signal_id], ...AGGREGATES);
      return;
    case 'plan_draft_ready':
      inv(qc, ['plan-drafts'], ['candidate-signals'], ['today']);
      return;
    case 'plan_triggered':
      inv(qc, ['plans'], ['today']);
      return;
    case 'notification': {
      const n = projectNotification(e.data as Notification);
      if (n.version <= notificationVersion(qc, n.id)) return;
      updateNotificationPages(qc, [n]);
      // 不按merged_count或事件数自增未读：只重读服务端行计数。
      inv(qc, ['notifications']);
      return;
    }
    case 'report':
      inv(qc, ['daily-reports'], ['daily-report', (e.data as StreamEventMap['report']).date], ['today']);
      return;
    case 'data_status':
      inv(qc, ...AGGREGATES);
      return;
    case 'data_licence':
      // Me.data_licence_status 驱动全站证书横幅；['me'] 前缀同时覆盖 /me/data-licence
      inv(qc, ['me']);
      return;
    default:
      return;
  }
}

/** 断线重连成功后：可能错过了超出服务端 10 分钟保留期的事件，未读数与聚合视图各补拉一次 */
export async function resyncAfterReconnect(qc: QueryClient, full = false) {
  inv(qc, ['notifications'], ...AGGREGATES);
  const [rows, count] = await Promise.all([
    qc.fetchQuery({ queryKey: full ? nk.reset : nk.catchup, queryFn: ({ signal }) => readUnreadNotifications(signal, full), staleTime: 0, retry: false }),
    // 独立于活动计数查询：实时事件会取消/替代其refetch，不应误把正常取消当补读失败。
    qc.fetchQuery({ queryKey: nk.catchupCount, queryFn: ({ signal }) => apiGet<{ count: number }>('/notifications/unread-count', undefined, signal), staleTime: 0, retry: false }),
  ]);
  qc.setQueryData(['notifications', 'unread-count'], count);
  updateNotificationPages(qc, rows);
}

/** 同id只覆盖较新版本；新行匹配当前筛选才加入第一页，不改任何服务端游标。 */
export function updateNotificationPages(qc: QueryClient, rows: Notification[]) {
  const byId = new Map(rememberNotificationVersions(qc, rows).map((n) => [n.id, n]));
  for (const [key] of qc.getQueriesData<InfiniteData<Paged<Notification>>>({ queryKey: ['notifications', 'pages'] })) {
    const filter = key[2] && typeof key[2] === 'object' ? key[2] as Record<string, unknown> : {};
    const matches = (n: Notification) => (!filter.unread || n.read_at === null) && (!filter.kind || n.kind === filter.kind);
    qc.setQueryData<InfiniteData<Paged<Notification>>>(key, (old) => {
      if (!old?.pages.length) return old;
      const known = new Set(old.pages.flatMap((page) => page.items.map((n) => n.id)));
      const additions = [...byId.values()].filter((n) => !known.has(n.id) && matches(n));
      return { ...old, pages: old.pages.map((page, i) => ({ ...page, items: latestNotifications([
        ...(i === 0 ? additions : []), ...page.items.map((raw) => {
          const n = projectNotification(raw); const incoming = byId.get(n.id);
          return incoming && incoming.version > n.version ? incoming : n;
        }),
      ]).filter(matches) })) };
    });
  }
}
/** 仅在本次已登录连接生命周期内记事件id；不持久化，不以事件数计算未读。 */
/** T-A31冻结的1024事件id先进先出容量；逐通知version仍是最终防重。 */
export const STREAM_EVENT_DEDUP_LIMIT = 1024;
export function createStreamConsumer(qc: QueryClient, onReset?: (reset: StreamEventMap['reset']) => void) {
  const seen = new Set<string>();
  return (message: SseMessage) => {
    const e = parseStreamMessage(message); if (!e || e.type === 'heartbeat') return;
    if (e.type === 'reset') { seen.clear(); onReset?.(e.data as StreamEventMap['reset']); return; }
    if (e.id && seen.has(e.id)) return;
    if (e.id) { seen.add(e.id); if (seen.size > STREAM_EVENT_DEDUP_LIMIT) { const first = seen.values().next().value; if (first) seen.delete(first); } }
    applyStreamEvent(qc, e);
  };
}
