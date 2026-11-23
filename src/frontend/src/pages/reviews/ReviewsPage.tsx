import { Button, Input, Table } from 'antd';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { useState, type FormEvent } from 'react';
import { useCreateReview, useReviews } from '../../api/reviewQueries';
import type { ReviewCreate, ReviewSummary } from '../../api/types';
import { DataStatusTag, EmptyState, ErrorBox } from '../../components/common';
import { fmtTime } from '../../lib/format';
import { REVIEW_BENCHMARK_NOTE } from '../../lib/reviewMetrics';

const trim = (value: string) => value.trim();

export function ReviewsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState('');
  const filter = { security_code: params.get('security_code') ?? '', plan_id: params.get('plan_id') ?? '' };
  const list = useReviews(filter);
  const create = useCreateReview();
  const setFilter = (key: 'security_code' | 'plan_id', value: string) => {
    const next = new URLSearchParams(params);
    const v = trim(value);
    if (v) next.set(key, v); else next.delete(key);
    setParams(next, { replace: true });
  };
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const planId = trim(String(form.get('plan_id') ?? ''));
    const code = trim(String(form.get('security_code') ?? '')).toUpperCase();
    const start = String(form.get('period_start') ?? '');
    const end = String(form.get('period_end') ?? '');
    if (!planId && !code) { setFormError('计划或证券至少填写一项。'); return; }
    if (!start || !end || start > end) { setFormError('起止日期必须有序。'); return; }
    setFormError('');
    const body: ReviewCreate = {
      plan_id: planId || null, security_code: code || null, period_start: start, period_end: end,
      plan_version_ids: [], trade_ids: [], lessons: trim(String(form.get('lessons') ?? '')) || null,
      tags: String(form.get('tags') ?? '').split(',').map(trim).filter(Boolean), judgement: [],
    };
    create.mutate(body, { onSuccess: (review) => navigate(`/reviews/${review.id}`) });
  };
  return (
    <div className="page-scroll page" data-testid="reviews-page">
      <div className="detail-head"><h2 className="page-title" style={{ margin: 0 }}>复盘</h2><Button onClick={() => setCreating((v) => !v)} data-testid="new-review">新建复盘</Button></div>
      <div className="muted small" style={{ marginBottom: 10 }}>记录计划与证券的复盘笔记。指标缺口和数据截至时间以接口返回为准，缺失时显示“未知”。<span data-testid="review-benchmark"> · {REVIEW_BENCHMARK_NOTE}</span></div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <Input.Search aria-label="证券代码筛选" placeholder="证券代码" value={filter.security_code} onChange={(e) => setFilter('security_code', e.target.value)} onSearch={(v) => setFilter('security_code', v)} style={{ width: 190 }} data-testid="review-filter-security" />
        <Input.Search aria-label="计划筛选" placeholder="计划 ID" value={filter.plan_id} onChange={(e) => setFilter('plan_id', e.target.value)} onSearch={(v) => setFilter('plan_id', v)} style={{ width: 240 }} data-testid="review-filter-plan" />
      </div>
      {creating ? (
        <form className="panel" onSubmit={submit} data-testid="review-create-form" style={{ marginBottom: 12 }}>
          <div className="panel-head"><span className="panel-title">新建复盘</span></div>
          <div style={{ display: 'grid', gap: 8, maxWidth: 620 }}>
            <label>计划 ID<input name="plan_id" placeholder="可选，至少填写计划或证券" /></label>
            <label>证券代码<input name="security_code" placeholder="如 600000.SH" /></label>
            <div style={{ display: 'flex', gap: 8 }}><label style={{ flex: 1 }}>起始日期<input type="date" name="period_start" /></label><label style={{ flex: 1 }}>结束日期<input type="date" name="period_end" /></label></div>
            <label>复盘笔记<textarea name="lessons" rows={3} /></label>
            <label>标签<input name="tags" placeholder="用逗号分隔，如 执行纪律,仓位" /></label>
            {!create.isError ? null : <ErrorBox error={create.error} prefix="保存复盘失败" />}
            {formError ? <div className="small error-box" role="alert" data-testid="review-form-error">{formError}</div> : null}
            <div><Button type="primary" htmlType="submit" loading={create.isPending} data-testid="submit-review">保存复盘</Button></div>
          </div>
        </form>
      ) : null}
      {list.isError ? <ErrorBox error={list.error} /> : null}
      <Table<ReviewSummary> rowKey="id" size="small" loading={list.isPending} dataSource={list.items} pagination={false} data-testid="reviews-table"
        locale={{ emptyText: <EmptyState title="暂无复盘记录" description="新建一条复盘后，计划和证券记录会显示在这里。" /> }}
        columns={[
          { title: '证券 / 计划', key: 'subject', render: (_: unknown, review) => <Link to={`/reviews/${review.id}`} data-testid={`review-link-${review.id}`}>{review.security_code ?? '未填证券'}{review.plan_id ? <span className="muted small"> · 计划 {review.plan_id}</span> : null}</Link> },
          { title: '复盘区间', key: 'period', render: (_: unknown, r) => <span className="mono">{r.period_start} ～ {r.period_end}</span> },
          { title: '当前版本', dataIndex: 'current_version_no', width: 95, render: (v: number | null) => v === null ? '—' : `第 ${v} 版` },
          { title: '数据状态', key: 'status', width: 120, render: (_: unknown, r) => <DataStatusTag status={r.data_status} asOf={r.data_as_of} gaps={r.gaps} /> },
          { title: '数据截至', key: 'data_as_of', width: 150, render: (_: unknown, r) => <span className="mono small">{r.data_as_of ? fmtTime(r.data_as_of) : '未知'}</span> },
          { title: '创建时间', dataIndex: 'created_at', width: 150, render: (v: string) => <span className="mono small">{fmtTime(v)}</span> },
        ]}
      />
      {list.hasNextPage ? <Button onClick={() => void list.fetchNextPage()} loading={list.isFetchingNextPage} style={{ marginTop: 8 }}>加载更多</Button> : null}
      <div className="muted small" style={{ marginTop: 8 }}>时间显示为北京时间，数据截至时间缺失时显示“未知”。</div>
    </div>
  );
}
