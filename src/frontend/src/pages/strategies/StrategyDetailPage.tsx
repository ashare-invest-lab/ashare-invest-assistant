import { labelOf } from '../../lib/explanations';
import { useState } from 'react';
import { Link, useParams } from 'react-router';
import { Empty, Segmented, Table, Tag } from 'antd';
import { useStrategyDetailTracking, useStrategyTemplates, useStrategyVersion } from '../../api/strategyQueries';
import type { StrategyTemplate, StrategyTracking, StrategyVersionDetail } from '../../api/strategyTypes';
import { ErrorBox, Loading } from '../../components/common';
import { StrategyTrackingStats } from '../../components/TrackingStats';
import { DIMENSION, HORIZON, LIFECYCLE, RULE_ROLE } from '../../i18n/labels';
import { isHighRisk } from '../../lib/strategyRisk';

const displayValue = (value: unknown) => value === undefined || value === null ? '—' : JSON.stringify(value);

function CurrentVersion({ template }: { template: StrategyTemplate }) {
  const [scope, setScope] = useState<StrategyTracking['scope']>('mine');
  const version = useStrategyVersion(template.id, template.current_version.id);
  const tracking = useStrategyDetailTracking(template.id, template.current_version.id, scope);
  const detail = version.data;

  return (
    <>
      <h2 className="page-title">{template.name} {isHighRisk(detail?.risk_level ?? template.risk_level) ? <Tag color="red">高风险</Tag> : null}</h2>
      <p className="mono muted">{template.key}</p>
      <p>周期：{template.horizons.length ? template.horizons.map((h) => (labelOf(HORIZON, h) ?? '未知')).join('、') : '未声明适用周期'}</p>
      <p>健康度：{template.health ? `${template.health.state} · n=${template.health.n} · 权重 ${template.health.weight}` : '暂无健康度'}</p>
      <p>当前版本：v{template.current_version.version_no} · {(detail?.lifecycle ?? template.current_version.lifecycle) === 'simulating' ? '模拟中' : (labelOf(LIFECYCLE, detail?.lifecycle ?? template.current_version.lifecycle) ?? '未知')}</p>
      {version.isPending ? <Loading /> : version.isError ? <ErrorBox error={version.error} prefix="策略版本加载失败" /> : detail ? (
        <section className="panel">
          <h3>版本配置</h3>
          <p>参数哈希：<span className="mono">{detail.param_hash}</span></p>
          <p>父版本 ID：{detail.parent_version_id ?? '无'}</p>
          <p>知识卡版本 ID：{detail.card_version_id ?? '—'}</p>
          <p>内部检验：{detail.internal_check.done ? '已做' : '未做'}；方法：{detail.internal_check.method_types.join('、') || '—'}；日期：{detail.internal_check.checked_on ?? '—'}</p>
          {detail.rules !== undefined ? (
            <>
              <h4>规则</h4>
              <Table<NonNullable<StrategyVersionDetail['rules']>[number]>
                size="small" pagination={false} dataSource={detail.rules} rowKey={(rule) => [rule.id, rule.dimension, rule.role, rule.expr].filter(Boolean).join('|') || 'rule'}
                locale={{ emptyText: '暂无规则' }}
                columns={[
                  { title: 'ID', dataIndex: 'id', render: (value) => value ?? '—' },
                  { title: '维度', key: 'dimension', render: (_, rule) => rule.dimension ? labelOf(DIMENSION, rule.dimension) ?? rule.dimension : '—' },
                  { title: '角色', key: 'role', render: (_, rule) => rule.role ? labelOf(RULE_ROLE, rule.role) ?? rule.role : '—' },
                  { title: '表达式', dataIndex: 'expr', render: (value) => <span style={{ overflowWrap: 'anywhere' }}>{value ?? '—'}</span> },
                ]}
              />
            </>
          ) : null}
          {detail.params_schema !== undefined ? (
            <>
              <h4>参数定义</h4>
              <Table
                size="small" pagination={false} rowKey="key"
                dataSource={Object.entries(detail.params_schema).map(([key, schema]) => ({ key, schema }))}
                locale={{ emptyText: '暂无参数定义' }}
                columns={[
                  { title: '键', dataIndex: 'key' },
                  { title: '类型', key: 'type', render: (_, row) => row.schema.type ?? '—' },
                  { title: '默认值', key: 'default', render: (_, row) => displayValue(row.schema.default) },
                  { title: '最小值', key: 'min', render: (_, row) => displayValue(row.schema.min) },
                  { title: '最大值', key: 'max', render: (_, row) => displayValue(row.schema.max) },
                  { title: '步长', key: 'step', render: (_, row) => displayValue(row.schema.step) },
                  { title: '说明', key: 'desc', render: (_, row) => row.schema.desc ?? '—' },
                ]}
              />
            </>
          ) : null}
          {(['stops', 'action_map'] as const).map((key) => detail[key] !== undefined ? (
            <div key={key}>
              <h4>{key === 'stops' ? '止损止盈配置' : '动作映射'}</h4>
              {Object.keys(detail[key]).length ? <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(detail[key], null, 2)}</pre> : <p className="muted">暂无配置</p>}
            </div>
          ) : null)}
        </section>
      ) : <Empty description="暂无版本配置" />}
      <section className="panel">
        <h3>策略版本模拟跟踪</h3>
        <Segmented<StrategyTracking['scope']> aria-label="跟踪范围" value={scope} onChange={setScope} options={[{ label: '本人', value: 'mine' }, { label: '全站', value: 'site' }]} />
        {tracking.isPending ? <Loading /> : tracking.isError ? <ErrorBox error={tracking.error} prefix="策略跟踪加载失败" /> : <StrategyTrackingStats data={tracking.data} />}
      </section>
    </>
  );
}

export function StrategyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const templates = useStrategyTemplates();
  const template = templates.data?.items.find((item) => item.id === id);

  return (
    <div className="page-scroll" data-testid="strategy-detail-page">
      <div className="page">
        <Link to="/strategies">返回策略库</Link>
        {templates.isPending ? <Loading /> : templates.isError ? <ErrorBox error={templates.error} prefix="策略列表加载失败" /> : template ? (
          <CurrentVersion key={`${template.id}-${template.current_version.id}`} template={template} />
        ) : <Empty description={templates.data.truncated ? '已加载列表中没有该模板，暂时无法打开详情。' : '策略列表中没有该模板'} />}
      </div>
    </div>
  );
}
