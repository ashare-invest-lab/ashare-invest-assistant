import { screen, within } from '@testing-library/react';
import { mockLoginAs } from '../../mocks/session';
import { STRATEGY_TEMPLATES } from '../../mocks/strategyHandlers';
import { renderTestRoute } from '../../test/renderTestRoute';

it('T-F71：发现入口替换到策略库，保留模板入口且不伪造筛选结果', async () => {
  mockLoginAs('demo_user');
  const router = await renderTestRoute('/discover');
  const page = await screen.findByTestId('strategies-page');

  expect(router.state.location.pathname).toBe('/strategies');
  expect(router.state.historyAction).toBe('REPLACE');
  expect(within(page).getByRole('heading', { name: '策略库' })).toBeVisible();
  expect(screen.queryByRole('heading', { name: '发现' })).not.toBeInTheDocument();
  expect(screen.queryByTestId('placeholder')).not.toBeInTheDocument();

  const template = STRATEGY_TEMPLATES[0];
  expect(within(page).getByRole('link', { name: template.name })).toHaveAttribute('href', `/strategies/${template.id}`);
  expect(screen.queryByText('筛选结果')).not.toBeInTheDocument();
  expect(screen.queryByText('命中证券')).not.toBeInTheDocument();
  expect(screen.queryByText('策略筛选')).not.toBeInTheDocument();
  expect(screen.queryAllByTestId(/strategy-screen|screen-result|screen-matched/i)).toHaveLength(0);
});
