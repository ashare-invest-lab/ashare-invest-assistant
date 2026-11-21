import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { TerminalRow } from '../../api/types';
import { WatchTable } from './WatchTable';

const row: TerminalRow = {
  security_code: '600000.SH',
  name: '示例银行',
  in_watchlist: true,
  focus: true,
  quote: {
    price: '10.24',
    change_pct: null,
    amount: null,
    t: '2026-11-02T10:31:00+08:00',
  },
  holding: null,
  suggestion: null,
  active_reason_count: 0,
  max_risk_level: null,
  data_status: 'fresh',
  data_as_of: '2026-11-02T10:31:00+08:00',
};

describe('T-F67 TerminalQuote nullable fields', () => {
  it('行情涨跌与成交额为空时显示缺失标记并保留现价', async () => {
    render(
      <WatchTable
        rows={[row]}
        loading={false}
        scope="all"
        onScope={() => undefined}
        selected={null}
        onSelect={() => undefined}
        onOpen={() => undefined}
      />,
    );

    const table = await screen.findByTestId('watch-table');
    expect(table.querySelector('.ag-row [col-id="price"]')).toHaveTextContent('10.24');
    expect(table.querySelector('.ag-row [col-id="chg"]')).toHaveTextContent('—');
    expect(table.querySelector('.ag-row [col-id="amount"]')).toHaveTextContent('—');
    expect(within(table).getAllByText('—').length).toBeGreaterThanOrEqual(2);
  });
});
