import type { ReactNode } from 'react';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { MemoryRouter } from 'react-router';
import type { TerminalRow, TodayFocusRow, TodayResponse } from '../api/types';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { WatchTable } from '../features/terminal/WatchTable';
import { TERMINAL_ROWS } from '../mocks/fixtures';
import { mockLoginAs } from '../mocks/session';
import { server } from '../mocks/server';
import { TodayPage } from './today/TodayPage';

type Column = { render?: (row: TerminalRow) => ReactNode };

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

beforeEach(() => mockLoginAs('demo_user'));

const base = TERMINAL_ROWS.find((row) => row.security_code === '510001.SH')!;
const empty = { items: [], more: false };

function today(items: TodayFocusRow[]): TodayResponse {
  return {
    account_id: null,
    server_time: '2026-11-02T10:30:00+08:00', trade_date: '2026-11-02', session: 'morning',
    market: { regime: null, regime_position_range: null, data_status: 'fresh' },
    focus: { items, more: false }, pending_plan_drafts: empty, released_reasons: empty,
    risk_flags: empty, invalidations_today: empty, daily_report: { date: '2026-11-02', status: 'not_yet' },
    reconciliation: { status: 'matched', as_of: null, diff_count: 0, important_count: 0 }, unread_notifications: 0,
    alerts: empty, plan_triggers: empty, data_gaps: empty, evidence: [],
  };
}

function renderWatch(rows: TerminalRow[]) {
  render(<WatchTable rows={rows} loading={false} scope="all" onScope={() => undefined} selected={null} onSelect={() => undefined} onOpen={() => undefined} />);
  return screen.getByTestId('watch-table');
}

it('未持仓自选 ETF 在终端和今日关注均按行级类型显示 3 位价格', async () => {
  const table = renderWatch([base]);
  expect(table).toHaveTextContent('3.940');

  server.use(http.get('/api/v1/today', () => HttpResponse.json(today([{ ...base, t_view: null }]))));
  render(<AppProviders client={makeQueryClient(true)}><MemoryRouter><TodayPage /></MemoryRouter></AppProviders>);
  const page = await screen.findByTestId('today-page');
  expect(page).toHaveTextContent('示例沪深300ETF');
  expect(page).toHaveTextContent('3.940');
});

it('行级类型缺失时回退持仓类型，未知类型使用默认位数且不抛错', () => {
  const holdingEtf = { ...base, holding: {
    qty: '100', sellable_qty: '100', cost_price: '3.90', weight_pct: '1.00', pnl: null, pnl_pct: null,
    security_type: 'etf' as const, estimated: false,
  } };
  const oldResponse = { ...holdingEtf } as Partial<TerminalRow>;
  delete oldResponse.security_type;
  const unknown = (value: string) => ({ ...base, security_type: value as TerminalRow['security_type'] });
  const table = renderWatch([
    holdingEtf,
    oldResponse as TerminalRow,
    { ...base, security_type: null, holding: null },
    unknown('__proto__'),
    unknown('constructor'),
    unknown('unfamiliar_type'),
  ]);
  expect(table).toHaveTextContent('3.940');
  expect(table.textContent?.match(/3\.94(?!0)/g)?.length).toBe(4);
});

it('quote 或价格为空时显示破折号且不抛错', () => {
  const nullPrice = { ...base, quote: { ...base.quote!, price: null } } as unknown as TerminalRow;
  const emptyPrice = { ...base, quote: { ...base.quote!, price: '' } };
  const table = renderWatch([{ ...base, quote: null }, nullPrice, emptyPrice]);
  expect(table).toHaveTextContent('—');
  expect(table.textContent).not.toMatch(/NaN|null|undefined/);
});
