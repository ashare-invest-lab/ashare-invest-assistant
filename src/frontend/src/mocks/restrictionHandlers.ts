import { http, HttpResponse } from 'msw';
import type { Restriction } from '../api/types';
import { page, notFound, validation } from './handlerUtils';

const API = '/api/v1';
const INITIAL: Restriction[] = [
  { id: 'restriction-example-block', kind: 'blocklist', target_type: 'security', target_id: '600000.SH', name: '示例银行', until: null, reason: '示例风险观察', created_at: '2026-11-18T09:30:00+08:00', removed_at: null },
  { id: 'restriction-example-cooling', kind: 'cooling_off', target_type: 'strategy', target_id: 'strategy-example-calm', name: '示例稳健策略', until: '2099-12-31T15:00:00+08:00', reason: '示例冷静期', created_at: '2026-11-19T10:00:00+08:00', removed_at: null },
  { id: 'restriction-example-mute', kind: 'mute', target_type: 'instance', target_id: 'instance-example-1', name: '示例策略实例', until: null, reason: '示例暂时屏蔽', created_at: '2026-11-20T11:00:00+08:00', removed_at: null },
  { id: 'restriction-example-expired', kind: 'cooling_off', target_type: 'security', target_id: '000001.SZ', name: '示例证券', until: '2020-01-01T00:00:00+08:00', reason: '示例已结束冷静期', created_at: '2026-10-01T09:00:00+08:00', removed_at: null },
];

let restrictions = INITIAL.map((item) => ({ ...item }));
export function resetRestrictions() {
  restrictions = INITIAL.map((item) => ({ ...item }));
}

function statusOf(item: Restriction): 'active' | 'expired' {
  return item.until && Date.parse(item.until) <= Date.now() ? 'expired' : 'active';
}

function resource(item: Restriction): Restriction {
  return { ...item, status: statusOf(item) };
}

const kinds = ['blocklist', 'cooling_off', 'mute'] as const;
const targetTypes = ['security', 'strategy', 'instance'] as const;

export const restrictionHandlers = [
  http.get(`${API}/restrictions`, ({ request }) => {
    const url = new URL(request.url);
    const kind = url.searchParams.get('kind');
    const targetType = url.searchParams.get('target_type');
    if (kind !== null && !(kinds as readonly string[]).includes(kind)) return validation('kind', 'kind 取值为 blocklist|cooling_off|mute');
    if (targetType !== null && !(targetTypes as readonly string[]).includes(targetType)) return validation('target_type', 'target_type 取值为 security|strategy|instance');
    const items = restrictions
      .filter((item) => item.removed_at === null && (!kind || item.kind === kind) && (!targetType || item.target_type === targetType))
      .map(resource);
    return HttpResponse.json(page(items, url));
  }),
  http.post(`${API}/restrictions`, async ({ request }) => {
    const raw = await request.json().catch(() => null);
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return validation('body', '请求体必须是对象');
    const body = raw as Record<string, unknown>;
    const allowed = ['kind', 'target_type', 'target_id', 'until', 'reason'];
    if (Object.keys(body).some((key) => !allowed.includes(key))) return validation('body', '请求体字段不符合契约');
    if (!kinds.includes(body.kind as (typeof kinds)[number])) return validation('kind', 'kind 取值为 blocklist|cooling_off|mute');
    if (!targetTypes.includes(body.target_type as (typeof targetTypes)[number])) return validation('target_type', 'target_type 取值为 security|strategy|instance');
    if (typeof body.target_id !== 'string' || !body.target_id.trim()) return validation('target_id', 'target_id 不能为空');
    if (body.until !== null && typeof body.until !== 'string') return validation('until', 'until 必须是 datetime 或 null');
    if (body.until !== null && Number.isNaN(Date.parse(body.until as string))) return validation('until', 'until 必须是有效 datetime');
    if (body.kind === 'cooling_off' && (body.until === null || Date.parse(body.until as string) <= Date.now())) return validation('until', '冷静期必须填写未来时间');
    if (body.reason !== null && typeof body.reason !== 'string') return validation('reason', 'reason 必须是字符串或 null');
    const created: Restriction = {
      id: `restriction-example-${Date.now().toString(36)}`,
      kind: body.kind as Restriction['kind'], target_type: body.target_type as Restriction['target_type'],
      target_id: body.target_id.trim(), until: body.until as string | null, reason: body.reason as string | null,
      name: null, created_at: new Date().toISOString(), removed_at: null,
    };
    restrictions = [created, ...restrictions];
    return HttpResponse.json({ ...resource(created), gaps: [] }, { status: 201 });
  }),
  http.delete(`${API}/restrictions/:id`, ({ params }) => {
    const id = String(params.id);
    const found = restrictions.find((item) => item.id === id && item.removed_at === null);
    if (!found) return notFound('限制项');
    const removedAt = new Date().toISOString();
    restrictions = restrictions.map((item) => item.id === id ? { ...item, removed_at: removedAt } : item);
    return HttpResponse.json({ id, removed_at: removedAt, recheck: { released_reason_ids: [], remaining_reason_ids: [] }, gaps: [] });
  }),
];
