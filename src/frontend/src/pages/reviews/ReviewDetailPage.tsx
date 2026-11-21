import { Button, Select, Tag } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { Link, useNavigate, useParams } from 'react-router';
import { useState } from 'react';
import { useReview, useReviewVersions } from '../../api/reviewQueries';
import type { ReviewOutcomeMetrics, ReviewVersion } from '../../api/types';
import { ApiError } from '../../api/client';
import { DataStatusTag, ErrorBox, GapNote, Loading } from '../../components/common';
import { labelOf } from '../../lib/explanations';
import { fmtTime } from '../../lib/format';

const TIMELINE_LABELS = { created: '创建复盘', version_created: '创建版本', snapshot: '生成快照' } as const;
const metricLabels: Record<keyof ReviewOutcomeMetrics, string> = {
  holding_return: '持有收益', benchmark_return: '基准收益', excess_return: '超额收益', max_drawdown: '最大回撤',
};

function MetricBlock({ version }: { version: ReviewVersion }) {
  return (
    <section className="panel" data-testid="review-metrics">
      <div className="panel-head"><span className="panel-title">结果指标</span></div>
      <div className="muted small">指标仅在来源、基准和计算公式可追溯时展示。当前示例未发布实绩指标。</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(100px, 1fr))', gap: 8, marginTop: 8 }}>
        {(Object.keys(metricLabels) as (keyof ReviewOutcomeMetrics)[]).map((key) => <div key={key}><div className="muted small">{metricLabels[key]}</div><b data-testid={`metric-${key}`}>{version.outcome_metrics[key]?.value ?? '—'}</b></div>)}
      </div>
      <GapNote status={version.data_status} gaps={version.gaps} asOf={version.data_as_of} testId="review-metric-gap" />
    </section>
  );
}

export function ReviewDetailPage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const review = useReview(id);
  const versions = useReviewVersions(id);
  const [selectedNo, setSelectedNo] = useState<number | null>(null);
  if (review.isPending) return <div className="page-scroll page" data-testid="review-detail"><Loading /></div>;
  if (review.isError || !review.data) {
    const notFound = review.error instanceof ApiError && review.error.status === 404;
    return <div className="page-scroll page" data-testid="review-detail">{notFound ? <div data-testid="review-not-found">复盘不存在或不属于你。<Link to="/reviews">返回复盘</Link></div> : <ErrorBox error={review.error} />}</div>;
  }
  const r = review.data;
  const allVersions = versions.items.length ? versions.items : r.versions ?? (r.current_version ? [r.current_version] : []);
  const defaultNo = r.current_version && allVersions.some((v) => v.version_no === r.current_version_no) ? r.current_version_no : allVersions[0]?.version_no ?? null;
  const shownNo = selectedNo ?? defaultNo;
  const version = allVersions.find((v) => v.version_no === shownNo) ?? r.current_version;
  return (
    <div className="page-scroll page" data-testid="review-detail">
      <div className="detail-head"><Button size="small" icon={<ArrowLeftOutlined />} onClick={() => navigate('/reviews')}>复盘列表</Button><h2 className="page-title" style={{ margin: 0 }}>{r.name ?? '复盘详情'}</h2><DataStatusTag status={r.data_status} asOf={r.data_as_of} gaps={r.gaps} /></div>
      <div className="muted small" style={{ margin: '6px 0 10px' }}>{r.security_code ? `证券 ${r.security_code}` : '未填证券'}{r.plan_id ? <> · 计划 <span className="mono">{r.plan_id}</span></> : null} · {r.period_start} ～ {r.period_end} · 创建于 {fmtTime(r.created_at)}</div>
      <GapNote status={r.data_status} gaps={r.gaps} asOf={r.data_as_of} testId="review-gap" />
      {version ? <>
        <section className="panel" data-testid="review-notes">
          <div className="panel-head"><span className="panel-title">第 {version.version_no} 版笔记</span>{version.tags.map((tag) => <Tag key={tag}>{tag}</Tag>)}</div>
          <p style={{ whiteSpace: 'pre-wrap' }}>{version.lessons || '暂无笔记。'}</p>
          <DataStatusTag status={version.data_status} asOf={version.data_as_of} gaps={version.gaps} />
          <div className="small muted" style={{ marginTop: 6 }}>版本创建于 {fmtTime(version.created_at)}</div>
        </section>
        <section className="panel" data-testid="review-judgement"><div className="panel-head"><span className="panel-title">判断标注</span></div>{version.attribution.judgement.length ? version.attribution.judgement.map((j, i) => <div key={`${j.condition_text}-${i}`} className="small" style={{ marginBottom: 4 }}><b>{j.condition_text}</b> · {j.fulfilled === null ? '未知' : j.fulfilled ? '已满足' : '未满足'}{j.note ? ` · ${j.note}` : ''}</div>) : <span className="muted small">暂无判断标注。</span>}</section>
        <MetricBlock version={version} />
      </> : <div className="panel">暂无版本内容。</div>}
      <section className="panel" data-testid="review-versions"><div className="panel-head"><span className="panel-title">版本</span><Select aria-label="复盘版本" value={shownNo ?? undefined} placeholder="选择版本" loading={versions.isPending} style={{ width: 140 }} options={allVersions.map((v) => ({ value: v.version_no, label: `第 ${v.version_no} 版` }))} onChange={(v: number) => setSelectedNo(v)} /></div>{allVersions.map((v) => <Button key={v.version_no} size="small" type={v.version_no === shownNo ? 'primary' : 'default'} onClick={() => setSelectedNo(v.version_no)} data-testid={`review-version-${v.version_no}`}>第 {v.version_no} 版 · {fmtTime(v.created_at)}</Button>)}</section>
      <section className="panel" data-testid="review-timeline"><div className="panel-head"><span className="panel-title">时间线</span></div>{r.timeline.length ? r.timeline.map((item, i) => <div key={`${item.at}-${i}`} className="small">{labelOf(TIMELINE_LABELS, item.kind) ?? '未知'} · {fmtTime(item.at)}{item.version_no ? ` · 第 ${item.version_no} 版` : ''}{item.evidence_ids.length ? ` · 证据 ${item.evidence_ids.join('、')}` : ''}</div>) : <span className="muted small">暂无时间线。</span>}</section>
      <div className="muted small">版本接口与复盘字段来自 T-A209 草案，尚未验证。</div>
    </div>
  );
}

