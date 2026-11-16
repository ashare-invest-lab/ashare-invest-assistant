import { Tag } from 'antd';
import type { MarketOverview } from '../../api/types';
import { ownValue } from '../../lib/enumValue';

/** T-A209 §3.2：只展示响应批次，不用客户端日期或指数样本补造 basis。 */
export function MarketBasis({ m }: { m: MarketOverview }) {
  const b = m.basis;
  const old = m.data_status === 'stale' || !!(b?.observed_date && b.observed_date < m.trade_date);
  const partial = m.data_status === 'partial' || (b?.missing ?? 0) > 0;
  const coverage = b && b.eligible !== null && b.eligible > 0 && b.observed !== null
    ? `${((b.observed / b.eligible) * 100).toFixed(1)}%` : '—';
  return (
    <section className="panel side-panel" data-testid="market-basis" aria-label="市场 basis">
      <b>basis</b> {partial ? <Tag color="gold">部分批</Tag> : null} {old ? <Tag>旧批</Tag> : null}
      {!b ? <div className="muted small">basis：—</div> : <>
        <div>snapshot_id：{b.snapshot_id ?? '—'} · observed_date：{b.observed_date ?? '—'}</div>
        <div className="muted">mode：{b.mode === null ? '—' : ownValue({ intraday: 'intraday', close: 'close' }, b.mode, '未知')} · scope：{b.scope} · source：{b.source ?? '—'}</div>
        <div>eligible：{b.eligible ?? '—'} · observed：{b.observed ?? '—'} · trading：{b.trading ?? '—'} · suspended：{b.suspended ?? '—'} · missing：{b.missing ?? '—'} · 覆盖率：{coverage}</div>
      </>}
    </section>
  );
}
