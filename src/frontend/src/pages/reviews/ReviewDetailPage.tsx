import { Button, Select, Tag } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router';
import { useCreateReviewVersion, useReview, useReviewVersions } from '../../api/reviewQueries';
import type { DataStatus } from '../../api/enums';
import type { Evidence, Gap, ReviewCreate, ReviewVersion } from '../../api/types';
import { ApiError } from '../../api/client';
import { DataStatusTag, ErrorBox, Loading } from '../../components/common';
import { EvidenceChips } from '../../components/EvidenceChips';
import { isNotApplicable } from '../../lib/dataGaps';
import { labelOf } from '../../lib/explanations';
import { fmtTime } from '../../lib/format';
import { formatReviewGapClauses, metricLabel, metricValueText, REVIEW_BENCHMARK_NOTE, REVIEW_METRIC_KEYS } from '../../lib/reviewMetrics';

const TIMELINE_LABELS = { review_version: '复盘版本', plan_version: '计划版本', trade: '成交' } as const;
const NOTE_STATUS: readonly DataStatus[] = ['stale', 'partial', 'unavailable'];

function ReviewGapNote({ status, gaps, asOf, testId = 'gap-note' }: { status: DataStatus; gaps: Gap[]; asOf?: string | null; testId?: string }) {
  if (!gaps.length && !NOTE_STATUS.includes(status)) return null;
  if (isNotApplicable(gaps)) {
    return (
      <div className="gap-note na small" role="note" aria-label="数据状态说明" data-testid={testId} data-status="not_applicable">
        <b>不适用</b>：该证券类型没有此类数据{gaps[0].message ? `（${gaps[0].message}）` : ''}
      </div>
    );
  }
  const licence = gaps.some((gap) => gap.reason === 'data_licence_unavailable');
  const onlySuspended = gaps.length > 0 && gaps.every((gap) => gap.reason === 'suspended');
  const head = onlySuspended && status !== 'stale' ? '停牌说明'
    : status === 'unavailable' ? '数据暂不可用' : status === 'stale' ? `数据已过期${asOf ? `（截至 ${fmtTime(asOf)}）` : ''}` : status === 'partial' ? '部分数据缺失' : '数据提示';
  const clauses = formatReviewGapClauses(gaps);
  return (
    <div className="gap-note small" role="note" aria-label="数据状态说明" data-testid={testId} data-status={status}>
      <b>{head}</b>
      {clauses.length ? '：' : null}
      {clauses.map((clause, index) => <span key={`${clause}-${index}`}>{index ? '；' : ''}{clause}</span>)}
      {licence ? <> <Link to="/settings/data-licence" data-testid="gap-licence-link">去设置数据证书 ›</Link></> : null}
    </div>
  );
}

function MetricBlock({ version }: { version: ReviewVersion }) {
  const metricGap = version.gaps.find((gap) => gap.key.startsWith('outcome_metrics.'));
  const outcomeMetrics = version.outcome_metrics && typeof version.outcome_metrics === 'object' ? version.outcome_metrics : null;
  return (
    <section className="panel" data-testid="review-metrics">
      <div className="panel-head"><span className="panel-title">实际成交复盘结果指标</span><span className="muted small" data-testid="review-benchmark">{REVIEW_BENCHMARK_NOTE}</span></div>
      <div className="muted small">指标缺口：{metricGap ? (metricGap.message || '未知') : '无'} · 数据截至：{version.data_as_of ? fmtTime(version.data_as_of) : '未知'}</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(100px, 1fr))', gap: 8, marginTop: 8 }}>
        {REVIEW_METRIC_KEYS.map((key) => <div key={key}><div className="muted small">{metricLabel(key) ?? '未知指标'}</div><b data-testid={`metric-${key}`}>{metricValueText(outcomeMetrics && Object.hasOwn(outcomeMetrics, key) ? outcomeMetrics[key] : null)}</b></div>)}
      </div>
      <ReviewGapNote status={version.data_status} gaps={version.gaps} asOf={version.data_as_of} testId="review-metric-gap" />
    </section>
  );
}

function EvidenceBlock({ evidence }: { evidence: Evidence[] }) {
  return (
    <section className="panel" data-testid="review-evidence">
      <div className="panel-head"><span className="panel-title">证据</span></div>
      {evidence.length ? evidence.map((item) => (
        <div key={item.id} className="small" style={{ marginBottom: 4 }}>
          <span className="mono">{item.key}</span> = {item.value === null ? '—' : String(item.value)}{item.unit ?? ''}
        </div>
      )) : <span className="muted small">暂无证据</span>}
    </section>
  );
}

function versionBody(review: { plan_id: string | null; security_code: string | null; period_start: string; period_end: string }, version: ReviewVersion, baseVersionNo: number): ReviewCreate & { base_version_no: number } {
  return {
    base_version_no: baseVersionNo,
    plan_id: review.plan_id,
    security_code: review.security_code,
    period_start: review.period_start,
    period_end: review.period_end,
    plan_version_ids: version.plan_version_ids,
    trade_ids: version.trade_ids,
    lessons: version.lessons,
    tags: version.tags,
    judgement: version.attribution.judgement,
  };
}

export function ReviewDetailPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const review = useReview(id);
  const versions = useReviewVersions(id);
  const saveVersion = useCreateReviewVersion(id);
  if (review.isPending) return <div className="page-scroll page" data-testid="review-detail"><Loading /></div>;
  if (review.isError || !review.data) {
    const notFound = review.error instanceof ApiError && review.error.status === 404;
    return <div className="page-scroll page" data-testid="review-detail">{notFound ? <div data-testid="review-not-found">复盘不存在或不属于你。<Link to="/reviews">返回复盘</Link></div> : <ErrorBox error={review.error} />}</div>;
  }
  const r = review.data;
  const evidence = r.evidence ?? [];
  const allVersions = versions.items.length ? versions.items : (r.current_version ? [r.current_version] : []);
  const defaultNo = r.current_version && allVersions.some((v) => v.version_no === r.current_version_no) ? r.current_version_no : allVersions[0]?.version_no ?? null;
  const requestedNo = Number(searchParams.get('version'));
  const queryNo = Number.isInteger(requestedNo) && requestedNo > 0 ? requestedNo : null;
  const shownNo = queryNo ?? defaultNo;
  const version = allVersions.find((v) => v.version_no === shownNo) ?? r.current_version;
  const selectVersion = (versionNo: number) => {
    const next = new URLSearchParams(searchParams);
    next.set('version', String(versionNo));
    setSearchParams(next, { replace: true });
  };
  const planVersionId = version?.plan_version_ids[0];
  const planHref = r.plan_id ? `/plans/${encodeURIComponent(r.plan_id)}${planVersionId ? `?plan_version_id=${encodeURIComponent(planVersionId)}` : ''}` : null;
  const currentVersion = r.current_version;
  const saveError = saveVersion.error;
  const conflictVersion = saveError instanceof ApiError && saveError.code === 'VERSION_CONFLICT' && typeof saveError.details?.current_version_no === 'number'
    ? saveError.details.current_version_no : null;
  const save = () => {
    if (!currentVersion || r.current_version_no === null) return;
    saveVersion.mutate(versionBody(r, currentVersion, r.current_version_no));
  };
  return (
    <div className="page-scroll page" data-testid="review-detail">
      <div className="detail-head"><Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/reviews')}>复盘列表</Button><h2 className="page-title" style={{ margin: 0 }}>{r.name ?? '复盘详情'}</h2><DataStatusTag status={r.data_status} asOf={r.data_as_of} gaps={r.gaps} /></div>
      <div className="muted small" style={{ margin: '6px 0 10px' }}>{r.security_code ? `证券 ${r.security_code}` : '未填证券'}{planHref ? <> · 计划 <Link to={planHref} data-testid="review-plan-link">{r.plan_id}</Link></> : null} · {r.period_start} ～ {r.period_end} · 创建于 {fmtTime(r.created_at)}</div>
      <ReviewGapNote status={r.data_status} gaps={r.gaps} asOf={r.data_as_of} testId="review-gap" />
      {version ? <>
        <section className="panel" data-testid="review-notes">
          <div className="panel-head"><span className="panel-title">第 {version.version_no} 版笔记</span>{version.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</div>
          <p style={{ whiteSpace: 'pre-wrap' }}>{version.lessons || '暂无笔记。'}</p>
          <DataStatusTag status={version.data_status} asOf={version.data_as_of} gaps={version.gaps} />
          <div className="small muted" style={{ marginTop: 6 }}>版本创建于 {fmtTime(version.created_at)}</div>
          {version.trade_ids.length ? <div className="small" style={{ marginTop: 6 }}>成交引用：{version.trade_ids.map((tradeId) => <Link key={tradeId} to={`/portfolio?tab=trades&trade_id=${encodeURIComponent(tradeId)}`} data-testid={`review-trade-link-${tradeId}`}>{tradeId}</Link>)}</div> : null}
        </section>
        <section className="panel" data-testid="review-judgement"><div className="panel-head"><span className="panel-title">判断标注</span></div>{version.attribution.judgement.length ? version.attribution.judgement.map((j, i) => <div key={`${j.condition_text}-${i}`} className="small" style={{ marginBottom: 4 }}><b>{j.condition_text}</b> · {j.fulfilled === null ? '未知' : j.fulfilled ? '已满足' : '未满足'}{j.note ? ` · ${j.note}` : ''}</div>) : <span className="muted small">暂无判断标注。</span>}</section>
        <MetricBlock version={version} />
      </> : <div className="panel">暂无版本内容。</div>}
      <EvidenceBlock evidence={evidence} />
      <section className="panel" data-testid="review-versions">
        <div className="panel-head"><span className="panel-title">版本</span><Select aria-label="复盘版本" value={shownNo ?? undefined} placeholder="选择版本" loading={versions.isPending} style={{ width: 140 }} options={allVersions.map((v) => ({ value: v.version_no, label: `第 ${v.version_no} 版` }))} onChange={(v: number) => selectVersion(v)} /></div>
        {allVersions.map((v) => <Button key={v.version_no} size="small" type={v.version_no === shownNo ? 'primary' : 'default'} onClick={() => selectVersion(v.version_no)} data-testid={`review-version-${v.version_no}`}>第 {v.version_no} 版 · {fmtTime(v.created_at)}</Button>)}
        <Button size="small" onClick={save} loading={saveVersion.isPending} disabled={!currentVersion || r.current_version_no === null} data-testid="review-save-version">保存为新版本</Button>
        {conflictVersion !== null ? <div className="small error-box" role="alert" data-testid="review-version-save-error">保存失败：当前已是第 {conflictVersion} 版，请重新加载。</div> : saveError ? <ErrorBox error={saveError} prefix="保存新版本失败" /> : null}
      </section>
      <section className="panel" data-testid="review-timeline"><div className="panel-head"><span className="panel-title">时间线</span></div>{r.timeline.length ? r.timeline.map((item, i) => { const label = labelOf(TIMELINE_LABELS, item.kind); return <div key={`${item.at}-${i}`} className="small"><span className={label ? undefined : 'muted'}>{label ?? '未知'}</span> · {fmtTime(item.at)}{item.version_no ? ` · 第 ${item.version_no} 版` : ''}{item.evidence_ids.length ? <> · <EvidenceChips ids={item.evidence_ids} evidence={evidence} /></> : null}</div>; }) : <span className="muted small">暂无时间线。</span>}</section>
    </div>
  );
}
