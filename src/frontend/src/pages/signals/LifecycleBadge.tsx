import { labelOf } from '../../lib/explanations';
import { Tag, Tooltip } from 'antd';
import type { Lifecycle } from '../../api/enums';
import { LIFECYCLE } from '../../i18n/labels';
import { LIFECYCLE_BADGE } from '../../i18n/signalLabels';

/** “模拟中 / 观察中”等非正式生命周期的徽标；已发布不显示 */
export function LifecycleBadge({ lifecycle }: { lifecycle: Lifecycle }) {
  const b = labelOf(LIFECYCLE_BADGE, lifecycle);
  if (!b) return labelOf(LIFECYCLE, lifecycle) ? null : <Tag data-testid="lifecycle-badge">未知</Tag>;
  return (
    <Tooltip title={b.tip}>
      <Tag color={b.color} data-testid="lifecycle-badge">{(labelOf(LIFECYCLE, lifecycle) ?? '未知')}</Tag>
    </Tooltip>
  );
}
