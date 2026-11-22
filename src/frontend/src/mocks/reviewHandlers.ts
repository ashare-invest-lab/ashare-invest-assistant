import { http, HttpResponse } from 'msw';
import type { ReviewCreate, ReviewDetail, ReviewOutcomeMetrics, ReviewVersion, ReviewVersionCreate } from '../api/types';
import { errorBody, notFound, page, validation } from './handlerUtils';

const API = '/api/v1';
const gap = (key: string, reason: 'no_source' | 'not_yet_published' | 'user_input_missing', message: string) => ({ key, reason, message });
const outcomeMetricKeys = ['holding_return', 'benchmark_return', 'excess_return', 'max_drawdown'] as const;
const outcomeMetricGaps = (reason: 'no_source' | 'not_yet_published', message: string) => outcomeMetricKeys.map((key) => gap(`outcome_metrics.${key}`, reason, message));
// 口径未定稿，夹具不造具体指标数值。接入真接口沿用现有 IS_MOCK（VITE_USE_MOCK=false + VITE_API_PROXY），不新增开关或依赖。
const emptyMetrics = (periodStart: string, periodEnd: string): ReviewOutcomeMetrics => {
  const stat = () => ({ value: null, n: 0, window: `${periodStart}/${periodEnd}`, small_sample: true });
  return { holding_return: stat(), benchmark_return: stat(), excess_return: stat(), max_drawdown: stat() };
};
const now = '2026-11-20T16:30:00+08:00';
const seed = (): ReviewDetail[] => {
  const complete: ReviewVersion = {
    id: 'review-version-example-1', version_no: 1,
    plan_version_ids: ['plan-version-example-1'], trade_ids: [], snapshot_id: null,
    lessons: '先记录执行条件，再复核结果。', tags: ['执行纪律'],
    attribution: { judgement: [{ condition_text: '按计划执行', fulfilled: true, note: '示例标注' }], execution: [], market: [] },
    outcome_metrics: emptyMetrics('2026-10-01', '2026-11-01'), created_at: now, data_status: 'partial', data_as_of: null,
    gaps: [gap('trade_ids', 'user_input_missing', '缺少可关联成交记录'), ...outcomeMetricGaps('no_source', '缺少价格、基准或公式来源，指标暂不计算')],
  };
  const pending: ReviewVersion = {
    ...complete, id: 'review-version-example-2', plan_version_ids: [],
    lessons: null, tags: ['等待结果期'], attribution: { judgement: [], execution: [], market: [] },
    outcome_metrics: emptyMetrics('2026-11-10', '2026-12-31'),
    data_status: 'pending', gaps: outcomeMetricGaps('not_yet_published', '结果期尚未结束，暂不发布指标'),
  };
  const base = (id: string, planId: string | null, code: string | null, start: string, end: string, version: ReviewVersion): ReviewDetail => ({
    id, plan_id: planId, security_code: code, name: code ? '示例银行' : null, period_start: start, period_end: end,
    current_version_no: version.version_no, created_at: now, data_status: version.data_status, data_as_of: version.data_as_of,
    gaps: version.gaps, current_version: version, evidence: [],
    timeline: [{ kind: 'review_version', at: now, resource_id: id, version_no: 1, evidence_ids: [] }],
  });
  const legacy: ReviewDetail = {
    id: 'review-example-legacy', plan_id: null, security_code: '000001.SZ', name: '演示电子',
    period_start: '2026-09-01', period_end: '2026-09-30', current_version_no: null, created_at: now,
    data_status: 'unavailable', data_as_of: null,
    gaps: [gap('outcome_metrics', 'no_source', '没有当前版本，结果指标暂无来源')], current_version: null, evidence: [], timeline: [],
  };
  return [base('review-example-1', 'plan-example-1', '600000.SH', '2026-10-01', '2026-11-01', complete), base('review-example-2', null, '600000.SH', '2026-11-10', '2026-12-31', pending), legacy];
};

const initialReviews = seed();
let reviews = initialReviews;
let versionStore = new Map<string, ReviewVersion[]>(initialReviews.map((review) => [review.id, review.current_version ? [review.current_version] : []]));
const idempotent = new Map<string, { text: string; response: ReviewDetail }>();
export const resetReviews = () => {
  reviews = seed();
  versionStore = new Map(reviews.map((review) => [review.id, review.current_version ? [review.current_version] : []]));
  idempotent.clear();
};
const detail = (id: string) => reviews.find((review) => review.id === id) ?? null;
const conflict = (currentVersionNo: number) => HttpResponse.json(errorBody('VERSION_CONFLICT', '版本号已变化', { current_version_no: currentVersionNo }), { status: 409 });

export const reviewHandlers = [
  http.get(`${API}/reviews`, ({ request }) => {
    const url = new URL(request.url);
    const code = url.searchParams.get('security_code');
    const planId = url.searchParams.get('plan_id');
    return HttpResponse.json(page(reviews.filter((r) => (!code || r.security_code === code) && (!planId || r.plan_id === planId)), url));
  }),
  http.get(`${API}/reviews/:id/versions/:versionNo`, ({ params }) => {
    const items = versionStore.get(String(params.id)) ?? [];
    const version = items.find((v) => v.version_no === Number(params.versionNo));
    return version ? HttpResponse.json(version) : notFound('复盘版本');
  }),
  http.get(`${API}/reviews/:id/versions`, ({ params, request }) => {
    const review = detail(String(params.id));
    return review ? HttpResponse.json(page(versionStore.get(review.id) ?? [], new URL(request.url))) : notFound('复盘');
  }),
  http.get(`${API}/reviews/:id`, ({ params }) => {
    const review = detail(String(params.id));
    return review ? HttpResponse.json(review) : notFound('复盘');
  }),
  http.post(`${API}/reviews`, async ({ request }) => {
    const body = await request.json() as Partial<ReviewCreate>;
    const key = request.headers.get('Idempotency-Key');
    const text = JSON.stringify(body);
    if (key) {
      const prior = idempotent.get(`create:${key}`);
      if (prior) return prior.text === text ? HttpResponse.json(prior.response, { status: 201 }) : HttpResponse.json(errorBody('IDEMPOTENCY_CONFLICT', '幂等键已用于其他请求'), { status: 409 });
    }
    if (!body.plan_id && !body.security_code) return validation('plan_id', '计划或证券至少填一项');
    if (!body.period_start || !body.period_end || body.period_start > body.period_end) return validation('period_start', '起止日期必须有序');
    const id = `review-created-${reviews.length + 1}`;
    const version: ReviewVersion = {
      id: `${id}-version-1`, version_no: 1, plan_version_ids: body.plan_version_ids ?? [], trade_ids: body.trade_ids ?? [], snapshot_id: null,
      lessons: body.lessons ?? null, tags: body.tags ?? [],
      attribution: { judgement: body.judgement ?? [], execution: [], market: [] }, outcome_metrics: emptyMetrics(body.period_start, body.period_end), created_at: now,
      data_status: 'partial', data_as_of: null, gaps: [gap('trade_ids', 'user_input_missing', '缺少可关联成交记录'), ...outcomeMetricGaps('no_source', '缺少价格、基准或公式来源，指标暂不计算')],
    };
    const created: ReviewDetail = {
      id, plan_id: body.plan_id ?? null, security_code: body.security_code ?? null, name: body.security_code ? '示例证券' : null,
      period_start: body.period_start, period_end: body.period_end, current_version_no: 1, created_at: now,
      data_status: version.data_status, data_as_of: version.data_as_of, gaps: version.gaps, current_version: version, evidence: [],
      timeline: [{ kind: 'review_version', at: now, resource_id: id, version_no: 1, evidence_ids: [] }],
    };
    reviews = [created, ...reviews];
    versionStore.set(id, [version]);
    if (key) idempotent.set(`create:${key}`, { text, response: created });
    return HttpResponse.json(created, { status: 201 });
  }),
  http.post(`${API}/reviews/:id/versions`, async ({ params, request }) => {
    const review = detail(String(params.id));
    if (!review) return notFound('复盘');
    const body = await request.json() as Partial<ReviewVersionCreate>;
    const key = request.headers.get('Idempotency-Key');
    const text = JSON.stringify(body);
    if (key) {
      const prior = idempotent.get(`version:${review.id}:${key}`);
      if (prior) return prior.text === text ? HttpResponse.json(prior.response, { status: 201 }) : HttpResponse.json(errorBody('IDEMPOTENCY_CONFLICT', '幂等键已用于其他请求'), { status: 409 });
    }
    const previous = review.current_version;
    const currentVersionNo = review.current_version_no;
    if (!previous || currentVersionNo === null) return validation('base_version_no', '复盘没有当前版本');
    if (body.base_version_no !== currentVersionNo) return conflict(currentVersionNo);
    const version: ReviewVersion = {
      ...previous,
      id: `${review.id}-version-${currentVersionNo + 1}`,
      version_no: currentVersionNo + 1,
      plan_version_ids: body.plan_version_ids ?? previous.plan_version_ids,
      trade_ids: body.trade_ids ?? previous.trade_ids,
      lessons: body.lessons ?? previous.lessons,
      tags: body.tags ?? previous.tags,
      attribution: { ...previous.attribution, judgement: body.judgement ?? previous.attribution.judgement },
      created_at: now,
    };
    const updated: ReviewDetail = {
      ...review,
      current_version_no: version.version_no,
      current_version: version,
      data_status: version.data_status,
      data_as_of: version.data_as_of,
      gaps: version.gaps,
      timeline: [...review.timeline, { kind: 'review_version', at: now, resource_id: version.id, version_no: version.version_no, evidence_ids: [] }],
      evidence: review.evidence ?? [],
    };
    reviews = reviews.map((item) => item.id === review.id ? updated : item);
    versionStore.set(review.id, [...(versionStore.get(review.id) ?? []), version]);
    if (key) idempotent.set(`version:${review.id}:${key}`, { text, response: updated });
    return HttpResponse.json(updated, { status: 201 });
  }),
];
