import type { ReactNode } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { TerminalResponse, TerminalRow } from '../api/types';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { ChartPanel } from '../features/terminal/ChartPanel';
import { TerminalPage } from '../features/terminal/TerminalPage';
import { WatchTable } from '../features/terminal/WatchTable';
import { TERMINAL_LICENCE_UNAVAILABLE_EXAMPLE, TERMINAL_ROWS } from '../mocks/fixtures';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { quoteCloseTagText } from '../lib/quoteDisplay';

type Column = { render?: (row: TerminalRow) => ReactNode };

vi.mock('../components/DataGrid', () => ({
  DataGrid: ({ testId, rows, columns, onRowClick }: {
    testId?: string;
    rows: TerminalRow[];
    columns: Column[];
    onRowClick?: (row: TerminalRow) => void;
  }) => (
    <div data-testid={testId}>
      {rows.map((row) => (
        <div key={row.security_code} data-row-code={row.security_code} onClick={() => onRowClick?.(row)}>
          {columns.map((column, index) => (column.render ? <div key={index} data-column-index={index}>{column.render(row)}</div> : null))}
        </div>
      ))}
    </div>
  ),
}));

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));

beforeEach(() => mockLoginAs('demo_user'));

function renderWatch(rows: TerminalRow[]) {
  render(<WatchTable rows={rows} loading={false} scope="all" onScope={() => undefined} selected={null} onSelect={() => undefined} onOpen={() => undefined} />);
  return screen.getByTestId('watch-table');
}

function renderChart(row: TerminalRow) {
  render(<AppProviders client={makeQueryClient(true)}><ChartPanel row={row} suggestion={undefined} tradeDate="2026-11-02" /></AppProviders>);
  return screen.getByTestId('quote-head');
}

function terminalBody(rows: TerminalRow[]): TerminalResponse {
  return {
    account_id: null, server_time: '2026-11-02T10:31:00+08:00', trade_date: '2026-11-02', session: 'closed',
    account: null, rows, truncated: false, unread_notifications: 0,
  };
}

function renderTerminal() {
  const router = createMemoryRouter([{ path: '/terminal', element: <TerminalPage /> }], { initialEntries: ['/terminal'] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
}

describe('T-F80 终端行情显示', () => {
  it('quoteCloseTagText 只接受 stale 与有值时点，并按北京时间取收盘日', () => {
    for (const status of ['__proto__', 'constructor', 'unknown', null, undefined, 'fresh', 'unavailable']) {
      expect(quoteCloseTagText(status, '2026-10-30T15:00:00+08:00')).toBeNull();
    }
    expect(quoteCloseTagText('stale', '')).toBeNull();
    expect(quoteCloseTagText('stale', '2026-10-30T15:00:00+08:00')).toBe('收盘价·10-30');
    for (const t of ['2026-10-30T07:00:00Z', '2026-10-29T23:00:00-08:00']) {
      expect(quoteCloseTagText('stale', t)).toBe('收盘价·10-30');
    }
  });

  it('默认终端夹具保留 688001 收盘回退数值，标签与数据时间分别取 t 和 data_as_of', async () => {
    const stale = TERMINAL_ROWS.find((row) => row.security_code === '688001.SH')!;
    expect(stale.quote).toMatchObject({ price: '86.90', change_pct: '-1.81', amount: null, t: '2026-10-30T15:00:00+08:00' });
    expect(stale.data_as_of).toBe('2026-11-02T08:20:00+08:00');

    const table = renderWatch([stale]);
    expect(within(table).getByTestId('quote-stale-tag')).toHaveTextContent('收盘价·10-30');
    expect(table).toHaveTextContent('86.90');
    expect(table).toHaveTextContent('—');
    expect(table).toHaveTextContent('数据时间 2026-11-02 08:20');

    const head = renderChart(stale);
    expect(within(head).getByTestId('quote-stale-tag')).toHaveTextContent('收盘价·10-30');
    expect(head).toHaveTextContent('86.90');
    expect(head).toHaveTextContent('成交额 —');
    expect(head).not.toHaveTextContent('15:00');
    expect(head).toHaveTextContent('数据时间 2026-11-02 08:20');
  });

  it('终端证书不可用夹具清空价格、涨跌和成交额，不显示旧价或收盘标签', async () => {
    server.use(http.get('/api/v1/terminal', () => HttpResponse.json(terminalBody([TERMINAL_LICENCE_UNAVAILABLE_EXAMPLE]))));
    renderTerminal();
    await screen.findAllByText(TERMINAL_LICENCE_UNAVAILABLE_EXAMPLE.security_code);
    const table = screen.getByTestId('watch-table');
    for (const index of [1, 2, 3]) expect(table.querySelector(`[data-column-index="${index}"]`)).toHaveTextContent(/^—$/);
    expect(table).not.toHaveTextContent('86.90');
    expect(within(table).queryByTestId('quote-stale-tag')).not.toBeInTheDocument();
  });

  it('quote 为 null 时终端行显示破折号且不出现 NaN', () => {
    const row = { ...TERMINAL_ROWS[0], quote: null };
    const table = renderWatch([row]);
    expect(table).toHaveTextContent('—');
    expect(table.textContent).not.toMatch(/NaN|null|undefined/);
  });

  it.each([
    { quote: { ...TERMINAL_ROWS[0].quote!, price: null } },
    { quote: { ...TERMINAL_ROWS[0].quote!, price: '' } },
  ] as const)('quote 或运行时价格为空显示破折号且不出现 NaN', ({ quote }) => {
    const row = { ...TERMINAL_ROWS[0], quote } as unknown as TerminalRow;
    const table = renderWatch([row]);
    expect(table).toHaveTextContent('—');
    expect(table.textContent).not.toMatch(/NaN|null|undefined/);
    const head = renderChart(row);
    expect(head).toHaveTextContent('—');
    expect(head.textContent).not.toMatch(/NaN|null|undefined/);
  });

  it('默认终端选择 688001 后 quote-head 同样显示收盘标签', async () => {
    renderTerminal();
    await screen.findAllByText('688001.SH');
    const table = screen.getByTestId('watch-table');
    fireEvent.click(table.querySelector('[data-row-code="688001.SH"]')!);
    expect(await screen.findByTestId('quote-head')).toHaveTextContent('收盘价·10-30');
  });

  it.each(['__proto__', 'constructor', 'unknown', 'close', 'intraday'])('basis/mode=%s 不参与标签判断', (basis) => {
    const stale = TERMINAL_ROWS.find((row) => row.security_code === '688001.SH')!;
    const withBasis = { ...stale } as TerminalRow & Record<string, unknown>;
    Object.defineProperty(withBasis, basis === '__proto__' ? '__proto__' : 'basis', { value: basis, enumerable: true });
    const table = renderWatch([withBasis]);
    expect(within(table).getByTestId('quote-stale-tag')).toHaveTextContent('收盘价·10-30');

    cleanup();
    const fresh = { ...TERMINAL_ROWS[0], data_status: 'fresh' } as TerminalRow & Record<string, unknown>;
    Object.defineProperty(fresh, basis === '__proto__' ? '__proto__' : 'mode', { value: basis, enumerable: true });
    const freshTable = renderWatch([fresh]);
    expect(within(freshTable).queryByTestId('quote-stale-tag')).not.toBeInTheDocument();
  });

  it.each(['__proto__', 'constructor', 'unknown'])('未知 data_status=%s 显示未知且不打收盘标签', (status) => {
    const row = { ...TERMINAL_ROWS[0], data_status: status } as unknown as TerminalRow;
    const table = renderWatch([row]);
    expect(table).toHaveTextContent('未知');
    expect(within(table).queryByTestId('quote-stale-tag')).not.toBeInTheDocument();
  });
});
