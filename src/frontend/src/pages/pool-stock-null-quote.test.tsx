import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import type { Bar, BarsResponse } from '../api/types';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { server } from '../mocks/server';
import { mockLoginAs } from '../mocks/session';
import { StockPage } from './stock/StockPage';

vi.mock('../components/charts/KlineChart', () => ({ KlineChart: ({ bars }: { bars: Bar[] }) => <div data-testid="null-quote-kline">{bars.map((b) => `${b.t}:${b.close}`).join('|')}</div> }));
vi.mock('../components/charts/IntradayChart', () => ({ IntradayChart: () => <div data-testid="null-quote-minute" /> }));
vi.mock('../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div /> }));
const code = '600000.SH';
const stamp = '2026-11-02T10:31:00+08:00';
const bar: Bar = { t: '2026-11-02', open: '10', high: '11', low: '9', close: '10.24', pre_close: '10', volume: '100', amount: '1024', avg_price: null, is_final: true };
function arm(nullQuote: boolean, minutePreClose: boolean) {
  mockLoginAs('demo_user');
  server.use(
    http.get('/api/v1/quotes', () => HttpResponse.json({ items: [{ security_code: code, name: '合成行情',
      price: nullQuote ? null : '10.24', change_pct: nullQuote ? null : '2.40', volume: nullQuote ? null : '100', amount: nullQuote ? null : '1024',
      t: nullQuote ? null : stamp, data_as_of: nullQuote ? null : stamp, data_status: nullQuote ? 'unavailable' : 'fresh',
      gaps: nullQuote ? [{ key: 'quotes', reason: 'no_source', message: '合成本人行情缓存无来源' }] : [] }] })),
    http.get('/api/v1/securities/:code/bars', ({ request }) => {
      const query = new URL(request.url).searchParams;
      const freq = query.get('freq') === '1m' ? '1m' : 'd';
      const adjust = query.get('adjust') === 'none' ? 'none' : 'qfq';
      const items = freq === 'd' ? [bar] : minutePreClose ? [{ ...bar, t: stamp }] : [];
      const body: BarsResponse = { security_code: code, name: '合成行情', freq, adjust, items, pre_close: minutePreClose ? '10' : null,
        next_before: null, adjust_as_of: adjust === 'none' ? null : '2026-11-02', data_status: 'fresh', data_as_of: stamp, gaps: [] };
      return HttpResponse.json(body);
    }),
  );
  render(<AppProviders client={makeQueryClient(true)}><MemoryRouter initialEntries={[`/stocks/${code}`]}><Routes><Route path="/stocks/:code" element={<StockPage />} /></Routes></MemoryRouter></AppProviders>);
}
function stat(head: HTMLElement, label: string) {
  return within(head).getByText(label, { selector: 'label' }).parentElement!.querySelector('b')!;
}
it.each([false, true])('HTTP行情全空、日K有值，分时前收存在=%s时页面及日K保留且不捏造零值', async (minutePreClose) => {
  arm(true, minutePreClose);
  const head = await screen.findByTestId('stock-head');
  await waitFor(() => expect(within(head).getByTestId('quote-gap-note')).toHaveTextContent('合成本人行情缓存无来源'));
  for (const label of ['今开', '最高', '最低', '昨收', '成交量', '成交额', '换手率', '总市值', '流通市值']) {
    expect(stat(head, label)).toHaveTextContent(/^—$/);
  }
  expect(head.querySelector('.q-price')).toHaveTextContent('—');
  expect(head.textContent).not.toMatch(/NaN|Invalid Date/);
  await userEvent.click(within(screen.getByTestId('price-chart')).getByText('日K', { exact: true }));
  expect(await screen.findByTestId('null-quote-kline')).toHaveTextContent('2026-11-02:10.24');
  expect(screen.getByTestId('profile-panel')).toBeInTheDocument();
});
it('有可信行情时保留当日OHLC和涨跌展示', async () => {
  arm(false, true);
  const head = await screen.findByTestId('stock-head');
  await waitFor(() => expect(stat(head, '今开')).toHaveTextContent(/^10$/));
  expect(stat(head, '昨收')).toHaveTextContent(/^10$/);
  expect(stat(head, '成交量')).toHaveTextContent('1手');
  expect(head.querySelector('.q-price')).toHaveTextContent('10.24');
  expect(head.textContent).toContain('+2.40%');
});
