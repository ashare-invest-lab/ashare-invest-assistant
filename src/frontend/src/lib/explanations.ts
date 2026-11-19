import type { ExplanationFallbackReason, Role } from '../api/enums';
export const EXPLANATION_FALLBACK_TEXT: Record<ExplanationFallbackReason, string> = {
  not_enabled: '未启用或未配置路由（未调用）',
  budget_exceeded: '预算超限',
  timeout: '模型调用超时',
  provider_error: '上游服务失败',
  validation_failed: '解释守卫验证拒绝',
};
export function explanationFallbackText(reason: string): string {
  return Object.hasOwn(EXPLANATION_FALLBACK_TEXT, reason) ? EXPLANATION_FALLBACK_TEXT[reason as ExplanationFallbackReason] : reason;
}
/** T-A36：目前尚无此前端页面；页面落地并注册路由后才可改为true。 */
export function hasAdminLlmUsagePage(): boolean { return false; }
export function adminLlmUsageHref(role: Role | undefined, callId: string | null, pageAvailable: boolean): string | null {
  return role === 'admin' && callId && pageAvailable ? `/admin/llm/usage?call_id=${encodeURIComponent(callId)}` : null;
}

/** 运行时枚举只认自有键；未知值由调用方保留原值或显示「未知」。 */
export function labelOf<T extends object>(map: T, key: PropertyKey | null | undefined): T[keyof T] | undefined {
  return key != null && Object.hasOwn(map, key) ? map[key as keyof T] : undefined;
}

/** 未知 Tag 不传 color，使用组件默认的中性色。 */
export function tagOf<T extends Record<string, { text: string; color?: string }>>(map: T, key: PropertyKey | null | undefined) {
  return labelOf(map, key) ?? { text: '未知', color: undefined };
}
