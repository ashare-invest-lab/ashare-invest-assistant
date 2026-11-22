import type { Gap, Stat } from '../api/types';
import { GAP_REASON } from '../i18n/labels';
import { ownValue } from './enumValue';

export const REVIEW_BENCHMARK_CODE = '000300.SH';
export const REVIEW_BENCHMARK_STATUS = '未验证';
export const REVIEW_BENCHMARK_NOTE = `产品计算基准 ${REVIEW_BENCHMARK_CODE}（${REVIEW_BENCHMARK_STATUS}）`;

export const REVIEW_METRIC_KEYS = ['holding_return', 'benchmark_return', 'excess_return', 'max_drawdown'] as const;
export type ReviewMetricKey = typeof REVIEW_METRIC_KEYS[number];

const REVIEW_METRIC_LABELS: Record<ReviewMetricKey, string> = {
  holding_return: '持有收益',
  benchmark_return: '基准收益',
  excess_return: '超额收益',
  max_drawdown: '最大回撤',
};

export function metricLabel(key: PropertyKey): string | undefined {
  return typeof key === 'string' && Object.hasOwn(REVIEW_METRIC_LABELS, key)
    ? REVIEW_METRIC_LABELS[key as ReviewMetricKey]
    : undefined;
}

/** 按缺口原因合并详情页说明，并只展示白名单中的结果指标名。 */
export function formatReviewGapClauses(gaps: readonly Gap[]): string[] {
  const groups = new Map<PropertyKey, { reason: string; metrics: string[]; messages: string[] }>();
  for (const gap of gaps) {
    const key = gap.reason as PropertyKey;
    let group = groups.get(key);
    if (!group) {
      group = { reason: ownValue(GAP_REASON, gap.reason, '未知'), metrics: [], messages: [] };
      groups.set(key, group);
    }
    const outcomePrefix = 'outcome_metrics.';
    const metric = typeof gap.key === 'string' && gap.key.startsWith(outcomePrefix)
      ? metricLabel(gap.key.slice(outcomePrefix.length)) : undefined;
    if (metric && !group.metrics.includes(metric)) group.metrics.push(metric);
    if (!group.messages.includes(gap.message)) group.messages.push(gap.message);
  }
  return Array.from(groups.values(), ({ reason, metrics, messages }) => {
    const metricText = metrics.length ? `${metrics.join('、')}：` : '';
    return `${reason}（${metricText}${messages.join('；')}）`;
  });
}

export function metricValueText(stat: unknown): string {
  if (typeof stat !== 'object' || stat === null || !Object.hasOwn(stat, 'value')) return '—';
  const value = (stat as Partial<Stat>).value;
  if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) return '—';
  return typeof value === 'number' && !Number.isFinite(value) ? '—' : String(value);
}
