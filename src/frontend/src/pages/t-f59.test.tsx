import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { DAILY_REPORT_LIST, DAILY_REPORTS, PREV_REPORT_DATE, REPORT_DATE } from '../mocks/fixtures';
import { errorBody } from '../mocks/handlerUtils';
import { server } from '../mocks/server';
import { DailyReportPage } from './DailyReportPage';

const API = '/api/v1';

function openReport() {
  const router = createMemoryRouter([
    { path: '/daily-reports/:date', element: <DailyReportPage /> },
  ], { initialEntries: [`/daily-reports/${REPORT_DATE}?filter=changed`] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
  return router;
}

it('首屏日期列表 500：提示并可重试，正文保持显示；成功后上一期可用', async () => {
  const seen: (string | null)[] = [];
  let detailReads = 0;
  server.use(http.get(`${API}/daily-reports/${REPORT_DATE}`, () => {
    detailReads++;
    return HttpResponse.json(DAILY_REPORTS[0]);
  }), http.get(`${API}/daily-reports`, ({ request }) => {
    seen.push(new URL(request.url).searchParams.get('cursor'));
    return seen.length === 1
      ? HttpResponse.json(errorBody('INTERNAL_ERROR', '日期列表读取失败'), { status: 500 })
      : HttpResponse.json({ items: DAILY_REPORT_LIST, next_cursor: null });
  }));
  const router = openReport();
  const error = await screen.findByRole('alert', { name: '日报日期列表错误' });
  expect(error).toHaveTextContent('日期列表加载失败');
  expect(screen.getByRole('button', { name: '上一期' })).toBeDisabled();
  const body = screen.getByTestId('report-explanation');
  const account = screen.getByTestId('report-account');
  const bodyText = body.textContent;
  expect(bodyText).not.toBe('');
  expect(body).toBeVisible();
  expect(account).toBeVisible();
  fireEvent.click(within(error).getByRole('button', { name: '重试' }));
  await waitFor(() => expect(screen.getByRole('button', { name: '上一期' })).toBeEnabled());
  expect(screen.queryByRole('alert', { name: '日报日期列表错误' })).not.toBeInTheDocument();
  expect(screen.getByTestId('report-explanation')).toBe(body);
  expect(body.textContent).toBe(bodyText);
  expect(screen.getByTestId('report-account')).toBe(account);
  expect(detailReads).toBe(1);
  expect(seen).toEqual([null, null]);
  expect(router.state.location.pathname).toBe(`/daily-reports/${REPORT_DATE}`);
  fireEvent.click(screen.getByRole('button', { name: '上一期' }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/daily-reports/${PREV_REPORT_DATE}`));
  expect(router.state.location.search).toBe('?filter=changed');
});

it('下一页失败保留已加载日期与正文，重试原游标成功后可选择更早日期', async () => {
  const user = userEvent.setup();
  const cursor = 'older/+?=&中文';
  const oldest = '2026-10-20';
  const seen: (string | null)[] = [];
  let nextReads = 0;
  server.use(http.get(`${API}/daily-reports/${oldest}`, () => HttpResponse.json({ ...DAILY_REPORTS[1], date: oldest })),
    http.get(`${API}/daily-reports`, ({ request }) => {
      const value = new URL(request.url).searchParams.get('cursor');
      seen.push(value);
      if (value === null) return HttpResponse.json({ items: DAILY_REPORT_LIST, next_cursor: cursor });
      nextReads++;
      return nextReads === 1
        ? HttpResponse.json(errorBody('INTERNAL_ERROR', '下一页读取失败'), { status: 500 })
        : HttpResponse.json({ items: [{ ...DAILY_REPORT_LIST[1], date: oldest }], next_cursor: null });
    }));
  const router = openReport();
  await screen.findByTestId('daily-report');
  await waitFor(() => expect(screen.getByRole('button', { name: '上一期' })).toBeEnabled());
  const body = screen.getByTestId('report-explanation');
  const bodyText = body.textContent;
  await user.click(screen.getByRole('combobox', { name: '选择日期' }));
  await user.click(await screen.findByText('加载更早…'));
  const error = await screen.findByRole('alert', { name: '日报日期列表错误' });
  expect(error).toHaveTextContent('更早日期加载失败，已加载日期保留');
  expect(body).toBeVisible();
  expect(body.textContent).toBe(bodyText);
  expect(screen.getByRole('button', { name: '上一期' })).toBeEnabled();
  await user.click(screen.getByRole('combobox', { name: '选择日期' }));
  expect(await screen.findByRole('option', { name: PREV_REPORT_DATE })).toBeInTheDocument();
  expect(screen.getByRole('option', { name: REPORT_DATE })).toBeInTheDocument();
  await user.keyboard('{Escape}');
  await user.click(within(error).getByRole('button', { name: '重试' }));
  await waitFor(() => expect(screen.queryByRole('alert', { name: '日报日期列表错误' })).not.toBeInTheDocument());
  expect(seen).toEqual([null, cursor, cursor]);
  expect(screen.getByTestId('report-explanation')).toBe(body);
  expect(body.textContent).toBe(bodyText);
  expect(router.state.location.pathname).toBe(`/daily-reports/${REPORT_DATE}`);
  await user.click(screen.getByRole('combobox', { name: '选择日期' }));
  const select = screen.getByRole('combobox', { name: '选择日期' });
  fireEvent.keyDown(select, { key: 'ArrowDown', keyCode: 40 });
  fireEvent.keyDown(select, { key: 'ArrowDown', keyCode: 40 });
  expect(await screen.findByRole('option', { name: oldest })).toBeInTheDocument();
  expect(screen.getByRole('option', { name: PREV_REPORT_DATE })).toBeInTheDocument();
  expect(screen.queryByText('加载更早…')).not.toBeInTheDocument();
  fireEvent.keyDown(select, { key: 'Enter', keyCode: 13 });
  await waitFor(() => expect(router.state.location.pathname).toBe(`/daily-reports/${oldest}`));
  expect(router.state.location.search).toBe('?filter=changed');
});

it('正常日期列表可导航，不显示错误或重试', async () => {
  const router = openReport();
  await screen.findByTestId('daily-report');
  await waitFor(() => expect(screen.getByRole('button', { name: '上一期' })).toBeEnabled());
  expect(screen.queryByRole('alert', { name: '日报日期列表错误' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: '重试' })).not.toBeInTheDocument();
  expect(screen.getByTestId('report-explanation')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: '上一期' }));
  await waitFor(() => expect(router.state.location.pathname).toBe(`/daily-reports/${PREV_REPORT_DATE}`));
  await waitFor(() => expect(screen.getByRole('button', { name: '下一期' })).toBeEnabled());
  expect(screen.queryByRole('alert', { name: '日报日期列表错误' })).not.toBeInTheDocument();
});
