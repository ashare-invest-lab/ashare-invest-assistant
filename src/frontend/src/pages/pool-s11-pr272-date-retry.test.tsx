import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import { DAILY_REPORT_LIST, DAILY_REPORTS, PREV_REPORT_DATE, REPORT_DATE } from '../mocks/fixtures';
import { errorBody } from '../mocks/handlerUtils';
import { server } from '../mocks/server';
import { DailyReportPage } from './DailyReportPage';

it('下一页重试挂起时切换已加载日期，保留列表错误并接收晚到日期，正文独立加载和报错', async () => {
  const cursor = 'older/+?=&中文';
  const oldest = '2026-10-20';
  const seenCursors: (string | null)[] = [];
  const seenDetails: string[] = [];
  let releasePage: () => void = () => {};
  let releaseDetail: () => void = () => {};
  const pendingPage = new Promise<void>((resolve) => { releasePage = resolve; });
  const pendingDetail = new Promise<void>((resolve) => { releaseDetail = resolve; });

  server.use(
    http.get('/api/v1/daily-reports', async ({ request }) => {
      const value = new URL(request.url).searchParams.get('cursor');
      seenCursors.push(value);
      if (value === null) return HttpResponse.json({ items: DAILY_REPORT_LIST, next_cursor: cursor });
      if (seenCursors.length === 2) {
        return HttpResponse.json(errorBody('INTERNAL_ERROR', '下一页读取失败'), { status: 500 });
      }
      await pendingPage;
      return HttpResponse.json({ items: [{ ...DAILY_REPORT_LIST[1], date: oldest }], next_cursor: null });
    }),
    http.get('/api/v1/daily-reports/:date', async ({ params }) => {
      const date = String(params.date);
      seenDetails.push(date);
      if (date === REPORT_DATE) return HttpResponse.json(DAILY_REPORTS[0]);
      if (date === PREV_REPORT_DATE) {
        await pendingDetail;
        return HttpResponse.json(DAILY_REPORTS[1]);
      }
      return HttpResponse.json(errorBody('NOT_FOUND', '未找到日报'), { status: 404 });
    }),
  );
  const user = userEvent.setup();
  const router = createMemoryRouter([
    { path: '/daily-reports/:date', element: <DailyReportPage /> },
  ], { initialEntries: [`/daily-reports/${REPORT_DATE}?filter=changed`] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);

  try {
    const originalBody = await screen.findByTestId('report-explanation');
    expect(originalBody).toBeVisible();
    await waitFor(() => expect(screen.getByRole('button', { name: '上一期' })).toBeEnabled());
    const switcher = screen.getByRole('combobox', { name: '选择日期' });
    await user.click(switcher);
    await user.click(await screen.findByText('加载更早…'));
    const listError = await screen.findByRole('alert', { name: '日报日期列表错误' });
    expect(listError).toHaveTextContent('更早日期加载失败，已加载日期保留');
    expect(originalBody).toBeVisible();
    await user.click(within(listError).getByRole('button', { name: '重试' }));
    await waitFor(() => expect(seenCursors).toEqual([null, cursor, cursor]));

    fireEvent.click(screen.getByRole('button', { name: '上一期' }));
    await waitFor(() => expect(seenDetails).toEqual([REPORT_DATE, PREV_REPORT_DATE]));
    expect(router.state.location.pathname).toBe(`/daily-reports/${PREV_REPORT_DATE}`);
    expect(router.state.location.search).toBe('?filter=changed');
    expect(screen.getByText('加载中…')).toBeVisible();
    expect(originalBody).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: '选择日期' })).toBe(switcher);
    expect(screen.getByRole('alert', { name: '日报日期列表错误' })).toBe(listError);
    expect(listError).toHaveTextContent('更早日期加载失败，已加载日期保留');

    releasePage();
    await waitFor(() => expect(listError).not.toBeInTheDocument());
    expect(screen.getByText('加载中…')).toBeVisible();
    expect(router.state.location.pathname).toBe(`/daily-reports/${PREV_REPORT_DATE}`);
    expect(screen.queryByTestId('report-explanation')).not.toBeInTheDocument();

    releaseDetail();
    expect(await screen.findByText(`日报日期 ${PREV_REPORT_DATE}`)).toBeVisible();
    expect(screen.getByTestId('report-no-account')).toBeVisible();
    await user.click(switcher);
    expect(await screen.findByRole('option', { name: oldest })).toBeInTheDocument();
    expect(screen.queryByText('加载更早…')).not.toBeInTheDocument();
    await user.keyboard('{Escape}');
    fireEvent.click(screen.getByRole('button', { name: '上一期' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('NOT_FOUND');
    expect(router.state.location.pathname).toBe(`/daily-reports/${oldest}`);
    expect(router.state.location.search).toBe('?filter=changed');
    expect(screen.queryByTestId('report-explanation')).not.toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: '选择日期' })).toBe(switcher);
    expect(screen.queryByRole('alert', { name: '日报日期列表错误' })).not.toBeInTheDocument();
    expect(seenCursors).toEqual([null, cursor, cursor]);
    expect(seenDetails).toEqual([REPORT_DATE, PREV_REPORT_DATE, oldest]);
  } finally {
    releasePage();
    releaseDetail();
  }
});
