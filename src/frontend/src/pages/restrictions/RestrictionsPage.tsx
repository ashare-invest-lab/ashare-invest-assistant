import { useState } from 'react';
import { Button, Input, Select, Space, Table, Tag } from 'antd';
import { useSearchParams } from 'react-router';
import { ENUMS, RESTRICTION_TARGET_TYPES, type RestrictionKind, type RestrictionTargetType } from '../../api/enums';
import { useCreateRestriction, useDeleteRestriction, useRestrictions, type RestrictionCreate } from '../../api/restrictionQueries';
import type { Restriction } from '../../api/types';
import { CursorPager } from '../../components/CursorPager';
import { ErrorBox } from '../../components/common';
import { GAP_REASON, RESTRICTION_KIND, RESTRICTION_STATUS, RESTRICTION_TARGET_TYPE } from '../../i18n/labels';
import { fmtTime } from '../../lib/format';
import { labelOf } from '../../lib/explanations';

const KINDS = ENUMS.restriction_kind as readonly RestrictionKind[];
const TARGET_TYPES = RESTRICTION_TARGET_TYPES;
const EMPTY_FORM: RestrictionCreate = { kind: 'blocklist', target_type: 'security', target_id: '', until: null, reason: null };

function parseChoice<T extends string>(value: string | null, choices: readonly T[]): T | undefined {
  return value && (choices as readonly string[]).includes(value) ? value as T : undefined;
}

function toApiUntil(value: string): string | null {
  return value ? `${value}:00+08:00` : null;
}

export function RestrictionsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const filter = {
    kind: parseChoice(searchParams.get('kind'), KINDS),
    target_type: parseChoice(searchParams.get('target_type'), TARGET_TYPES),
  };
  const list = useRestrictions(filter);
  const create = useCreateRestriction();
  const remove = useDeleteRestriction();
  const [form, setForm] = useState(EMPTY_FORM);
  const [now, setNow] = useState(0);
  const untilInput = form.until?.replace(/:00\+08:00$/, '').slice(0, 16) ?? '';
  const futureUntil = form.until !== null && now > 0 && !Number.isNaN(Date.parse(form.until)) && Date.parse(form.until) > now;
  const canSubmit = !!form.target_id.trim() && (form.kind !== 'cooling_off' || futureUntil);

  const setParam = (key: 'kind' | 'target_type', value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value); else next.delete(key);
    setSearchParams(next, { replace: true });
  };

  const submit = () => {
    if (!canSubmit || create.isPending) return;
    create.mutate({ ...form, target_id: form.target_id.trim(), reason: form.reason?.trim() || null }, {
      onSuccess: () => setForm(EMPTY_FORM),
    });
  };

  return (
    <div className="page-scroll page" data-testid="restrictions-page">
      <h2 className="page-title">禁投 / 冷静期 / 屏蔽</h2>
      <div className="muted small" style={{ marginBottom: 10 }}>管理会影响候选信号执行性的限制。时间均按北京时间显示。</div>

      <section className="panel" data-testid="restriction-form">
        <h4>新增限制</h4>
        <Space wrap align="end">
          <label>类型<Select aria-label="限制类型" value={form.kind} style={{ width: 130, display: 'block' }} onChange={(v: RestrictionKind) => setForm((old) => ({ ...old, kind: v }))} options={KINDS.map((k) => ({ value: k, label: labelOf(RESTRICTION_KIND, k) ?? '未知' }))} /></label>
          <label>目标类型<Select aria-label="目标类型" value={form.target_type} style={{ width: 130, display: 'block' }} onChange={(v: RestrictionTargetType) => setForm((old) => ({ ...old, target_type: v }))} options={TARGET_TYPES.map((t) => ({ value: t, label: labelOf(RESTRICTION_TARGET_TYPE, t) ?? '未知' }))} /></label>
          <label>目标 ID<Input aria-label="目标 ID" value={form.target_id} onChange={(e) => setForm((old) => ({ ...old, target_id: e.target.value }))} placeholder="例如 600000.SH" /></label>
          <label>截止时间<Input aria-label="截止时间" type="datetime-local" value={untilInput} onChange={(e) => { setNow(Date.now()); setForm((old) => ({ ...old, until: toApiUntil(e.target.value) })); }} /></label>
          <label>原因<Input aria-label="原因" value={form.reason ?? ''} onChange={(e) => setForm((old) => ({ ...old, reason: e.target.value || null }))} placeholder="可选" /></label>
          <Button type="primary" onClick={submit} disabled={!canSubmit} loading={create.isPending} data-testid="restriction-create">新增</Button>
        </Space>
        {form.kind === 'cooling_off' && !futureUntil ? <div className="warn small" role="alert" data-testid="cooling-off-validation">冷静期必须填写未来的截止时间</div> : null}
        {create.isError ? <ErrorBox error={create.error} /> : null}
      </section>

      <Space wrap style={{ margin: '12px 0' }}>
        <Select aria-label="筛选类型" value={filter.kind ?? ''} style={{ width: 150 }} onChange={(v: string) => setParam('kind', v)} options={[{ value: '', label: '全部类型' }, ...KINDS.map((k) => ({ value: k, label: labelOf(RESTRICTION_KIND, k) ?? '未知' }))]} />
        <Select aria-label="筛选目标类型" value={filter.target_type ?? ''} style={{ width: 150 }} onChange={(v: string) => setParam('target_type', v)} options={[{ value: '', label: '全部目标类型' }, ...TARGET_TYPES.map((t) => ({ value: t, label: labelOf(RESTRICTION_TARGET_TYPE, t) ?? '未知' }))]} />
      </Space>

      {list.isError ? <ErrorBox error={list.error} /> : null}
      {(list.first?.gaps ?? []).length ? (
        <div className="gap-alert small" data-testid="restriction-list-gaps">
          {(list.first?.gaps ?? []).map((gap, index) => <p key={`${gap.key}-${index}`}>缺口 · {labelOf(GAP_REASON, gap.reason) ?? '未知'}：{gap.message}</p>)}
        </div>
      ) : null}
      <Table<Restriction>
        rowKey="id" size="small" loading={list.isPending} dataSource={list.items} pagination={false}
        locale={{ emptyText: '暂无限制项。你可以在上方新增禁投、冷静期或屏蔽。' }} data-testid="restrictions-table"
        columns={[
          { title: '类型', key: 'kind', render: (_: unknown, row) => <Tag>{labelOf(RESTRICTION_KIND, row.kind) ?? '未知'}</Tag> },
          { title: '目标', key: 'target', render: (_: unknown, row) => <>{row.name ? <>{row.name} <span className="mono muted">{row.target_id}</span></> : <span className="mono">{row.target_id}</span>}</> },
          { title: '目标类型', key: 'target_type', render: (_: unknown, row) => labelOf(RESTRICTION_TARGET_TYPE, row.target_type) ?? '未知' },
          { title: '截止时间', dataIndex: 'until', render: (value: string | null) => value ? fmtTime(value) : '无截止时间' },
          { title: '原因', dataIndex: 'reason', render: (value: string | null) => value ?? '—' },
          { title: '状态', key: 'status', render: (_: unknown, row) => { const tag = labelOf(RESTRICTION_STATUS, row.status); return <Tag color={tag?.color ?? '#5a6170'}>{tag?.text ?? '未知'}</Tag>; } },
          { title: '创建时间', dataIndex: 'created_at', render: (value: string) => fmtTime(value) },
          { title: '操作', key: 'actions', render: (_: unknown, row) => <Button size="small" danger loading={remove.isPending && remove.variables === row.id} onClick={() => remove.mutate(row.id)} data-testid={`restriction-delete-${row.id}`}>删除</Button> },
        ]}
      />
      <CursorPager query={list} loaded={list.items.length} testId="restrictions-pager" />
      {remove.isError ? <ErrorBox error={remove.error} prefix="删除失败" /> : null}
      {remove.data ? (
        <div className="gap-alert small" data-testid="restriction-recheck">
          <p>删除后重查已释放 {remove.data.recheck.released_reason_ids.length} 项，仍有 {remove.data.recheck.remaining_reason_ids.length} 项。</p>
          {remove.data.gaps.length ? (
            <div data-testid="restriction-recheck-gaps">
              {remove.data.gaps.map((gap, index) => <p key={`${gap.key}-${index}`}>缺口 · {labelOf(GAP_REASON, gap.reason) ?? '未知'}：{gap.message}</p>)}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="muted small" style={{ marginTop: 8 }}>删除后将由系统重查不可执行原因，删除成功不等于已可交易。</div>
    </div>
  );
}
