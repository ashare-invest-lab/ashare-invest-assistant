import { act, render } from '@testing-library/react';
import type { QueryClient } from '@tanstack/react-query';
import { createMemoryRouter, type RouteObject } from 'react-router';
import { onTestFinished } from 'vitest';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { routes } from '../app/routes';
import { TestRouterProvider } from './TestRouterProvider';

/** Mount a real route after its initial lazy navigation, outside DOM query deadlines. */
export async function renderTestRoute(
  path: string,
  { client = makeQueryClient(true), routeObjects = routes }: { client?: QueryClient; routeObjects?: RouteObject[] } = {},
) {
  const viewport = { innerWidth: Object.getOwnPropertyDescriptor(window, 'innerWidth')!, innerHeight: Object.getOwnPropertyDescriptor(window, 'innerHeight')! };
  onTestFinished(() => { Object.defineProperties(window, viewport); });
  Object.defineProperty(window, 'innerWidth', { configurable: true, writable: true, value: 1440 });
  Object.defineProperty(window, 'innerHeight', { configurable: true, writable: true, value: 900 });
  const router = createMemoryRouter(routeObjects, { initialEntries: [path] });
  onTestFinished(() => {
    router.dispose();
    client.clear();
  });
  if (!router.state.initialized) {
    await new Promise<void>((resolve) => {
      const unsubscribe = router.subscribe((state) => {
        if (state.initialized) {
          unsubscribe();
          resolve();
        }
      });
    });
  }
  await act(async () => {
    render(<AppProviders client={client}><TestRouterProvider router={router} /></AppProviders>);
  });
  return router;
}
