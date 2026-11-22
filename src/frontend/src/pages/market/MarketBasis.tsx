import { Tag } from 'antd';
import type { MarketBasis as MarketBasisValue, MarketOverview } from '../../api/types';
import { ownValue } from '../../lib/enumValue';

/** 只展示后端给出的市场批次证据。没有批次时明确显示缺证，不从客户端时间推断。 */
export function BasisTrace({ basis, testId = 'basis-trace' }: { basis?: MarketBasisValue | null; testId?: string }) {
  if (!basis) return <div className="muted small" data-testid={testId}>市场批次：缺证</div>;
  const value = (item: string | number | null) => item ?? '缺证';
  const mode = basis.mode === null ? '缺证' : ownValue({ intraday: 'intraday', close: 'close' }, basis.mode, '未知');
  return (
    <div className="muted small" data-testid={testId}>
      市场批次：snapshot_id：{value(basis.snapshot_id)} · observed_date：{value(basis.observed_date)} · mode：{mode} · scope：{value(basis.scope)} · source：{value(basis.source)} · eligible：{value(basis.eligible)} · observed：{value(basis.observed)} · trading：{value(basis.trading)} · suspended：{value(basis.suspended)} · missing：{value(basis.missing)}
    </div>
  );
}

/** v0.2.11 §5.1：只展示响应批次，不用客户端日期或指数样本补造 basis。 */
export function MarketBasis({ m }: { m: MarketOverview }) {
  const b = m.basis ?? null;
  const old = m.data_status === 'stale' || !!(b?.observed_date && b.observed_date < m.trade_date);
  const partial = m.data_status === 'partial' || (b?.missing ?? 0) > 0;
  const coverage = b && b.eligible !== null && b.eligible > 0 && b.observed !== null
    ? `${((b.observed / b.eligible) * 100).toFixed(1)}%` : '—';
  return (
    <section className="panel side-panel" data-testid="market-basis" aria-label="市场 basis">
      <b>basis</b> {partial ? <Tag color="gold">部分批</Tag> : null} {old ? <Tag>旧批</Tag> : null}
      {!b ? <>
        <div className="muted small">basis：缺证</div>
        <div className="gap-note small" role="note" data-testid="market-basis-gap">无市场快照证据</div>
      </> : <>
        <BasisTrace basis={b} testId="market-basis-trace" />
        <div>覆盖率：{coverage === '—' ? '缺证' : coverage}</div>
      </>}
    </section>
  );
}
