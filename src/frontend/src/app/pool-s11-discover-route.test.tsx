import { screen, within } from '@testing-library/react';
import { mockLoginAs } from '../mocks/session';
import { STRATEGY_TEMPLATES } from '../mocks/strategyHandlers';
import { renderTestRoute } from '../test/renderTestRoute';

it('从发现链接进入现有策略库，并用规范路径替换历史记录', async () => {
  mockLoginAs('demo_user');
  const router = await renderTestRoute('/discover');
  const page = await screen.findByTestId('strategies-page');
  expect(within(page).getByRole('heading', { name: '策略库' })).toBeVisible();
  const template = STRATEGY_TEMPLATES[0];
  expect(within(page).getByRole('link', { name: template.name })).toHaveAttribute('href', `/strategies/${template.id}`);
  const nav = screen.getByRole('navigation', { name: '主导航' });
  expect(within(nav).getByRole('link', { name: '策略库' })).toHaveAttribute('aria-current', 'page');
  expect(router.state.location.pathname).toBe('/strategies');
  expect(router.state.historyAction).toBe('REPLACE');
});
