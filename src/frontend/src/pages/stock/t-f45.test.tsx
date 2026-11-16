import { render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import type { QuoteItem } from '../../api/types';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { STALE_QUOTE_EXAMPLE } from '../../mocks/fixtures';
import { server } from '../../mocks/server';
import { mockLoginAs } from '../../mocks/session';
import { StockPage } from './StockPage';

vi.mock('../../components/charts/KlineChart', () => ({ KlineChart: () => <div /> }));
vi.mock('../../components/charts/IntradayChart', () => ({ IntradayChart: () => <div /> }));
vi.mock('../../components/charts/FundFlowChart', () => ({ FundFlowChart: () => <div /> }));

function renderQuote(overrides?: Partial<QuoteItem>) {
  // 仅在本测试覆盖 /quotes，不改默认夹具里的 688001.SH。
  server.use(http.get('/api/v1/quotes', () => HttpResponse.json({
    items: [{ ...STALE_QUOTE_EXAMPLE.item, ...overrides } satisfies QuoteItem],
  })));
  renderStockPage();
}

function renderStockPage() {
  mockLoginAs('demo_user');
  render(<AppProviders client={makeQueryClient(true)}><MemoryRouter initialEntries={['/stocks/688001.SH']}>
    <Routes><Route path="/stocks/:code" element={<StockPage />} /></Routes>
  </MemoryRouter></AppProviders>);
}

it('MSW 收盘回退（K5）：价格和涨跌幅照常显示，标明收盘日，空 gaps 仍显示采集时点，价量不补零', async () => {
  renderQuote();
  const tag = await screen.findByTestId('quote-stale-tag');
  expect(tag).toHaveTextContent(/^收盘价·10-30$/);
  expect(tag.previousElementSibling).toHaveTextContent('86.90');
  const head = screen.getByTestId('stock-head');
  // 只约束 change_pct；前面可能还有依赖昨收夹具的涨跌额。
  expect(head.querySelector('.sh-quote')).toHaveTextContent('(-1.81%)');
  expect(within(head).getByTestId('quote-gap-note')).toHaveTextContent('数据已过期（截至 2026-11-02 08:20）');
  expect(head.querySelector('.sh-quote > .muted.small.mono')).not.toBeInTheDocument();
  expect(head.querySelector('.sh-quote')).not.toHaveTextContent('15:00');
  for (const label of ['成交量', '成交额']) {
    expect(within(head).getByText(label, { selector: 'label' }).parentElement!.querySelector('b')).toHaveTextContent(/^—$/);
  }
});

it('K5 data_licence_unavailable 完整响应：价格和涨跌幅为 —，显示原因及证书设置链接，无报错框', async () => {
  // fake：与 quotes_read.py 无可用证书时的完整 QuoteItem 一致，不从 stale 夹具补字段。
  // 未验证：证书不可用但有本人旧缓存时是否返回 stale 并保留数值。
  server.use(http.get('/api/v1/quotes', () => HttpResponse.json({
    items: [{
      security_code: '688001.SH',
      name: '虚构芯片',
      price: null,
      change_pct: null,
      volume: null,
      amount: null,
      t: null,
      data_status: 'unavailable',
      data_as_of: null,
      gaps: [{ key: 'quotes', reason: 'data_licence_unavailable', message: '本人数据证书不可用' }],
    } satisfies QuoteItem],
  })));
  renderStockPage();

  const note = await screen.findByTestId('quote-gap-note');
  const head = screen.getByTestId('stock-head');
  expect(head.querySelector('.sh-quote > .q-price')).toHaveTextContent(/^—$/);
  expect(head.querySelector('.sh-quote > .q-price + span')).toHaveTextContent(/^—$/);
  expect(within(head).queryByTestId('quote-stale-tag')).not.toBeInTheDocument();
  expect(within(note).getByText('数据暂不可用', { selector: 'b' })).toBeInTheDocument();
  expect(within(note).getByText('你的数据证书不可用（本人数据证书不可用）'))
    .toHaveAttribute('data-reason', 'data_licence_unavailable');
  const link = within(note).getByTestId('gap-licence-link');
  expect(link).toHaveTextContent('去设置数据证书 ›');
  expect(link).toHaveAttribute('href', '/settings/data-licence');
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
