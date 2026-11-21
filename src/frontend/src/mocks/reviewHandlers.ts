import { http, HttpResponse } from 'msw';
import type { ReviewCreate, ReviewDetail, ReviewOutcomeMetrics, ReviewVersion } from '../api/types';
import { errorBody, notFound, page, validation } from './handlerUtils';

const API = '/api/v1';
const gap = (key: string, reason: 'no_source' | 'not_yet_published' | 'user_input_missing', message: string) => ({ key, reason, message });
const emptyMetrics = (): ReviewOutcomeMetrics => {
  const stat = () => ({ value: null, n: 0, window: 'review_period', small_sample: true });
  return { holding_return: stat(), benchmark_return: stat(), excess_return: stat(), max_drawdown: stat() };
};
const now = '2026-11-20T16:30:00+08:00';
const seed = (): ReviewDetail[] => {
  const complete: ReviewVersion = {
    id: 'review-version-example-1', review_id: 'review-example-1', version_no: 1,
    plan_version_ids: ['plan-version-example-1'], trade_ids: [], snapshot_id: null,
    lessons: '先记录执行条件，再复核结果。', tags: ['执行纪律'],
    attribution: { judgement: [{ condition_text: '按计划执行', fulfilled: true, note: '示例标注' }], execution: [], market: [] },
    outcome_metrics: emptyMetrics(), created_at: now, data_status: 'partial', data_as_of: null,
    gaps: [gap('trade_ids', 'user_input_missing', '缺少可关联成交记录'), gap('outcome_metrics', 'no_source', '缺少价格、基准或公式来源，指标暂不计算')],
  };
  const pending: ReviewVersion = {
    ...complete, id: 'review-version-example-2', review_id: 'review-example-2', plan_version_ids: [],
    lessons: null, tags: ['等待结果期'], attribution: { judgement: [], execution: [], market: [] },
    data_status: 'pending', gaps: [gap('outcome_metrics', 'not_yet_published', '结果期尚未结束，暂不发布指标')],
  };
  const base = (id: string, planId: string | null, code: string | null, start: string, end: string, version: ReviewVersion): ReviewDetail => ({
    id, plan_id: planId, security_code: code, name: code ? '示例银行' : null, period_start: start, period_end: end,
    current_version_no: version.version_no, created_at: now, data_status: version.data_status, data_as_of: version.data_as_of,
    gaps: version.gaps, current_version: version, versions: [version],
    timeline: [{ kind: 'created', at: now, resource_id: id, version_no: 1, evidence_ids: [] }],
  });
  return [base('review-example-1', 'plan-example-1', '600000.SH', '2026-10-01', '2026-11-01', complete), base('review-example-2', null, '600000.SH', '2026-11-10', '2026-12-31', pending)];
};

let reviews = seed();
export const resetReviews = () => { reviews = seed(); };
const detail = (id: string) => reviews.find((review) => review.id === id) ?? null;

export const reviewHandlers = [
  http.get(`${API}/reviews`, ({ request }) => {
    const url = new URL(request.url);
    const code = url.searchParams.get('security_code');
    const planId = url.searchParams.get('plan_id');
    return HttpResponse.json(page(reviews.filter((r) => (!code || r.security_code === code) && (!planId || r.plan_id === planId)), url));
  }),
  http.get(`${API}/reviews/:id/versions/:versionNo`, ({ params }) => {
    const review = detail(String(params.id));
    const version = review?.versions?.find((v) => v.version_no === Number(params.versionNo));
    return version ? HttpResponse.json(version) : notFound('复盘版本');
  }),
  http.get(`${API}/reviews/:id/versions`, ({ params, request }) => {
    const review = detail(String(params.id));
    return review ? HttpResponse.json(page(review.versions ?? [], new URL(request.url))) : notFound('复盘');
  }),
  http.get(`${API}/reviews/:id`, ({ params }) => {
    const review = detail(String(params.id));
    return review ? HttpResponse.json(review) : notFound('复盘');
  }),
  http.post(`${API}/reviews`, async ({ request }) => {
    const body = await request.json() as Partial<ReviewCreate>;
    if (!body.plan_id && !body.security_code) return validation('plan_id', '计划或证券至少填一项');
    if (!body.period_start || !body.period_end || body.period_start > body.period_end) return validation('period_start', '起止日期必须有序');
    const id = `review-created-${reviews.length + 1}`;
    const version: ReviewVersion = {
      id: `${id}-version-1`, review_id: id, version_no: 1, plan_version_ids: body.plan_version_ids ?? [], trade_ids: body.trade_ids ?? [], snapshot_id: null,
      lessons: body.lessons ?? null, tags: body.tags ?? [],
      attribution: { judgement: body.judgement ?? [], execution: [], market: [] }, outcome_metrics: emptyMetrics(), created_at: now,
      data_status: 'partial', data_as_of: null, gaps: [gap('trade_ids', 'user_input_missing', '缺少可关联成交记录'), gap('outcome_metrics', 'no_source', '缺少价格、基准或公式来源，指标暂不计算')],
    };
    const created: ReviewDetail = {
      id, plan_id: body.plan_id ?? null, security_code: body.security_code ?? null, name: body.security_code ? '示例证券' : null,
      period_start: body.period_start, period_end: body.period_end, current_version_no: 1, created_at: now,
      data_status: version.data_status, data_as_of: null, gaps: version.gaps, current_version: version, versions: [version],
      timeline: [{ kind: 'created', at: now, resource_id: id, version_no: 1, evidence_ids: [] }],
    };
    reviews = [created, ...reviews];
    return HttpResponse.json(created, { status: 201 });
  }),
  http.post(`${API}/reviews/:id/versions`, () => HttpResponse.json(errorBody('VERSION_CONFLICT', '示例版本接口未验证'), { status: 409 })),
];
