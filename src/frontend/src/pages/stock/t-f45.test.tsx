import { act, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import type { QuoteItem } from '../../api/types';
import { mk } from '../../api/marketQueries';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { STALE_QUOTE_EXAMPLE } from '../../mocks/fixtures';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { StockPage } from './StockPage';

vi.mock('../../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));
vi.mock('../../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div /> }));

function renderQuote(overrides?: Partial<QuoteItem>, client = makeQueryClient(true)) {
  mockLoginAs('demo_user');
  // 仅在本测试覆盖 /quotes，不改默认夹具里的 688001.SH。
  server.use(http.get('/api/v1/quotes', () => HttpResponse.json({
    items: [{ ...STALE_QUOTE_EXAMPLE.item, ...overrides } satisfies QuoteItem],
  })));
  render(<AppProviders client={client}><MemoryRouter initialEntries={['/stocks/688001.SH']}>
    <Routes><Route path="/stocks/:code" element={<StockPage />} /></Routes>
  </MemoryRouter></AppProviders>);
}

it('MSW 收盘回退：价格旁标明收盘日，空 gaps 仍显示采集时点，价量不补零', async () => {
  renderQuote();
  const tag = await screen.findByTestId('quote-stale-tag');
  expect(tag).toHaveTextContent(/^收盘价·10-30$/);
  expect(tag.previousElementSibling).toHaveTextContent('86.90');
  const head = screen.getByTestId('stock-head');
  expect(within(head).getByTestId('quote-gap-note')).toHaveTextContent('数据已过期（截至 2026-11-02 08:20）');
  expect(head.querySelector('.sh-quote > .muted.small.mono')).not.toBeInTheDocument();
  expect(head.querySelector('.sh-quote')).not.toHaveTextContent('15:00');
  for (const label of ['成交量', '成交额']) {
    expect(within(head).getByText(label, { selector: 'label' }).parentElement!.querySelector('b')).toHaveTextContent(/^—$/);
  }
});

it('test_ta173_quotes_unavailable_hides_old_price_and_stale_tag', async () => {
  const client = makeQueryClient(true);
  renderQuote(undefined, client);
  const head = await screen.findByTestId('stock-head');
  expect(await within(head).findByTestId('quote-stale-tag')).toHaveTextContent(/^收盘价·10-30$/);
  expect(head.querySelector('.q-price')).toHaveTextContent(/^86\.90$/);
  expect(head.querySelector('.sh-quote')).toHaveTextContent('(-1.81%)');
  expect(within(head).getByTestId('quote-gap-note')).toHaveTextContent('截至 2026-11-02 08:20');
  expect(client.getQueryData(mk.quote('688001.SH'))).toEqual(STALE_QUOTE_EXAMPLE.item);

  const unavailable: QuoteItem = {
    security_code: '688001.SH', name: '演示芯片',
    price: null, change_pct: null, volume: null, amount: null, t: null, data_as_of: null,
    data_status: 'unavailable',
    gaps: [{ key: 'quotes', reason: 'data_licence_unavailable', message: '本人数据证书不可用' }],
  };
  const unavailableRequest = vi.fn(() => HttpResponse.json({ items: [unavailable] }));
  server.use(http.get('/api/v1/quotes', unavailableRequest));
  await act(async () => {
    await client.refetchQueries({ queryKey: mk.quote('688001.SH'), exact: true });
  });
  await waitFor(() => {
    expect(unavailableRequest).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(mk.quote('688001.SH'))).toEqual(unavailable);
    expect(within(head).getByTestId('quote-gap-note')).toHaveAttribute('data-status', 'unavailable');
  });
  expect(head).not.toHaveTextContent('86.90');
  expect(head).not.toHaveTextContent('-1.81%');
  expect(within(head).queryByTestId('quote-stale-tag')).not.toBeInTheDocument();
  expect(head).not.toHaveTextContent('收盘价·10-30');
  expect(head.querySelector('.q-price')).toHaveTextContent(/^—$/);
  expect(head.querySelector('.sh-quote > span.mono')).toHaveTextContent(/^—$/);
  for (const label of ['成交量', '成交额']) {
    expect(within(head).getByText(label, { selector: 'label' }).parentElement!.querySelector('b')).toHaveTextContent(/^—$/);
  }
  const note = within(head).getByTestId('quote-gap-note');
  expect(note.querySelector('[data-reason="data_licence_unavailable"]')).toHaveTextContent('本人数据证书不可用');
  expect(within(note).getByRole('link', { name: /去设置数据证书/ })).toHaveAttribute('href', '/settings/data-licence');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('test_ta173_quotes_stale_keeps_price_change_and_close_date', async () => {
  renderQuote();
  const tag = await screen.findByTestId('quote-stale-tag');
  const head = screen.getByTestId('stock-head');
  expect(head.querySelector('.q-price')).toHaveTextContent(/^86\.90$/);
  expect(head.querySelector('.sh-quote')).toHaveTextContent('(-1.81%)');
  expect(tag).toHaveTextContent(/^收盘价·10-30$/);
  expect(within(head).getByTestId('quote-gap-note')).toHaveTextContent('数据已过期（截至 2026-11-02 08:20）');
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it.each(['2026-10-30T07:00:00Z', '2026-10-29T23:00:00-08:00', '2026-10-29T23:30:00Z'])(
  '收盘标签按北京时间取日期，独立于进程 TZ：%s', async (t) => {
    renderQuote({ t });
    expect(await screen.findByTestId('quote-stale-tag')).toHaveTextContent(/^收盘价·10-30$/);
  },
);

it.each([
  { data_status: 'unavailable', price: null, change_pct: null, t: null, data_as_of: null },
  { data_status: 'unavailable' },
  { data_status: 'fresh' },
  { t: null },
] satisfies Partial<QuoteItem>[])('非 stale 或无收盘日时不显示标签：%j', async (overrides) => {
  renderQuote(overrides);
  const head = await screen.findByTestId('stock-head');
  await waitFor(() => expect(within(head).queryByText('行情加载中…')).not.toBeInTheDocument());
  expect(within(head).queryByTestId('quote-stale-tag')).not.toBeInTheDocument();
});
