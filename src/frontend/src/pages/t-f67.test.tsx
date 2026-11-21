import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import type { TerminalRow } from '../api/types';
import { TERMINAL_NULL_QUOTE_EXAMPLE } from '../mocks/fixtures';
import { WatchTable } from '../features/terminal/WatchTable';

type Column = { render?: (row: TerminalRow) => ReactNode };

// 只保留列渲染，避免该回归测试依赖 AG Grid 的布局测量。
vi.mock('../components/DataGrid', () => ({
  DataGrid: ({ testId, rows, columns }: { testId?: string; rows: TerminalRow[]; columns: Column[] }) => (
    <div data-testid={testId}>
      {rows.map((row) => (
        <div key={row.security_code}>
          {columns.map((column, index) => (column.render ? <div key={index}>{column.render(row)}</div> : null))}
        </div>
      ))}
    </div>
  ),
}));

it('WatchTable：持仓 ETF 现价固定显示 3 位小数', () => {
  const row: TerminalRow = {
    ...TERMINAL_NULL_QUOTE_EXAMPLE,
    quote: { ...TERMINAL_NULL_QUOTE_EXAMPLE.quote!, price: '3.94' },
    holding: {
      qty: '100', sellable_qty: '100', cost_price: '3.90', weight_pct: '1.00',
      pnl: '4.00', pnl_pct: '1.03', security_type: 'etf', estimated: false,
    },
  };
  render(<WatchTable rows={[row]} loading={false} scope="all" onScope={() => undefined} selected={row.security_code} onSelect={() => undefined} onOpen={() => undefined} />);
  expect(screen.getByTestId('watch-table')).toHaveTextContent('3.940');
});
