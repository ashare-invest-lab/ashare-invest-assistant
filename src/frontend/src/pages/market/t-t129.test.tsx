import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import type { MarketOverview } from '../../api/types';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { routes } from '../../app/routes';
import { MARKET_OVERVIEW } from '../../mocks/marketFixtures';
import { server } from '../../mocks/server';
import { preloadRoutes } from '../../test/preloadRoutes';

vi.mock('../stock/PriceChartPanel', () => ({
  PriceChartPanel: () => <div data-testid="index-chart" />,
}));

const marketRoutes = routes.flatMap((route) => route.children ?? []).filter(
  (route) => route.path === 'market' || route.path === 'market/overview',
);

beforeAll(() => preloadRoutes(marketRoutes));

const sectorEmpty = {
  kind: 'industry' as const,
  taxonomy: null,
  trade_date: null,
  items: [],
  sources: [],
  data_status: 'unavailable' as const,
  data_as_of: null,
  gaps: [{ key: 'sector_flows', reason: 'no_source' as const, message: '虚构板块来源缺失' }],
};

function mount(body: MarketOverview) {
  server.use(
    http.get('/api/v1/market/overview', () => HttpResponse.json(body)),
    http.get('/api/v1/market/sector-flows', () => HttpResponse.json(sectorEmpty)),
  );
  const router = createMemoryRouter(marketRoutes, { initialEntries: ['/market'] });
  return render(
    <AppProviders client={makeQueryClient(true)}>
      <RouterProvider router={router} />
    </AppProviders>,
  );
}

test('T-T129 market page exposes Beijing timing, basis state and gap reason', async () => {
  mount({
    ...MARKET_OVERVIEW,
    trade_date: '2026-11-13',
    session: 'closed',
    data_status: 'stale',
    data_as_of: '2026-11-12T15:00:00+08:00',
    basis: { ...MARKET_OVERVIEW.basis!, observed_date: '2026-11-12', mode: 'close', missing: 1 },
    gaps: [{ key: 'market.breadth', reason: 'no_source', message: '虚构宽度批次缺失' }],
  });
  await screen.findByTestId('market-basis');
  const page = screen.getByTestId('market-page');
  expect(page).toHaveTextContent('2026-11-13');
  expect(page).toHaveTextContent('已收盘');
  expect(page).toHaveTextContent('更新于 2026-11-12 15:00');
  expect(screen.getByTestId('market-basis')).toHaveTextContent('部分批');
  expect(screen.getByTestId('market-basis')).toHaveTextContent('旧批');
  expect(screen.getByTestId('market-gap-note')).toHaveTextContent('虚构宽度批次缺失');
});

test('T-T129 market page keeps null indicators and basis empty state explicit', async () => {
  mount({
    ...MARKET_OVERVIEW,
    basis: null,
    indices: [],
    breadth: null,
    turnover_total: null,
    data_status: 'unavailable',
    data_as_of: null,
    gaps: [{ key: 'market.breadth', reason: 'no_source', message: '虚构市场来源缺失' }],
  });
  await screen.findByTestId('market-basis');
  const page = screen.getByTestId('market-page');
  expect(page).toHaveTextContent('数据不可用（无数据时点）');
  expect(screen.getByTestId('market-basis')).toHaveTextContent('basis：—');
  expect(screen.getByTestId('market-basis')).toHaveTextContent('无市场快照证据');
  expect(screen.getByTestId('breadth-panel')).toHaveTextContent('涨跌家数暂不可用');
  expect(screen.getByTestId('market-gap-note')).toHaveTextContent('虚构市场来源缺失');
  expect(page.innerHTML).not.toMatch(/NaN|Infinity|undefined/);
});
