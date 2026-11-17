import { render, screen } from '@testing-library/react';
import { DataStatusTag, GapNote } from './common';

it('DataStatusTag 和 GapNote 共用秒级时间展示，不泄露微秒', () => {
  const asOf = '2026-11-13 15:06:59.586199';
  render(<>
    <DataStatusTag status="stale" asOf={asOf} gaps={[]} />
    <GapNote status="stale" asOf={asOf} gaps={[]} />
  </>);
  expect(screen.getByTestId('data-status-tag')).toHaveAccessibleDescription('数据时间 2026-11-13 15:06:59');
  expect(screen.getByTestId('gap-note')).toHaveTextContent('数据已过期（截至 2026-11-13 15:06:59）');
  expect(document.body).not.toHaveTextContent('.586199');
});
