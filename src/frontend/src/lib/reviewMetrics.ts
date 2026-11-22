import type { Stat } from '../api/types';

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

export function metricValueText(stat: unknown): string {
  if (typeof stat !== 'object' || stat === null || !Object.hasOwn(stat, 'value')) return '—';
  const value = (stat as Partial<Stat>).value;
  if (value === null || value === undefined || (typeof value === 'string' && value.trim() === '')) return '—';
  return typeof value === 'number' && !Number.isFinite(value) ? '—' : String(value);
}
