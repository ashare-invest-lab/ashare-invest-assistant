import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { NotFoundPage, PlaceholderPage } from './PlaceholderPage';

function renderPage(path: string) {
  render(<MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/future" element={<PlaceholderPage title="待接入页面" />} />
    <Route path="/terminal" element={<h2>交易终端</h2>} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes></MemoryRouter>);
}

it('展示页面标题、路径及接收到的筛选参数，返回交易终端', async () => {
  renderPage('/future?tab=released&status=pending%2Cstale&event=breakout');
  expect(screen.getByText('待接入页面')).toBeInTheDocument();
  expect(screen.getByText('/future')).toBeInTheDocument();
  expect(screen.getByText('tab=released')).toBeInTheDocument();
  expect(screen.getByText('status=pending,stale')).toBeInTheDocument();
  expect(screen.getByText('event=breakout')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '回到交易终端' }));
  expect(await screen.findByRole('heading', { name: '交易终端' })).toBeInTheDocument();
});

it('没有筛选参数时只展示页面说明', () => {
  renderPage('/future');
  expect(screen.getByText(/页面骨架已就位/)).toHaveTextContent('功能在后续任务按契约接入');
  expect(screen.queryByText(/已接收筛选参数/)).not.toBeInTheDocument();
});

it('未知路径显示页面不存在，允许返回交易终端', async () => {
  renderPage('/missing');
  expect(screen.getByText('页面不存在')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: '回到交易终端' }));
  expect(await screen.findByRole('heading', { name: '交易终端' })).toBeInTheDocument();
});
