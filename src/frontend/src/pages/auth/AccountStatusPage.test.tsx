import { fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter } from 'react-router';
import { TestRouterProvider } from '../../test/TestRouterProvider';
import { AccountStatusPage } from './AccountStatusPage';

function renderAt(search = '', state: { reason?: string | null } | null = null) {
  const router = createMemoryRouter([
    { path: '/account-status', element: <AccountStatusPage /> },
    { path: '/login', element: <h1>登录页面</h1> },
  ], { initialEntries: [{ pathname: '/account-status', search, state }] });
  render(<TestRouterProvider router={router} />);
}

describe('账号状态页', () => {
  it.each([
    ['pending', '账号正在审核中', '待审核', '管理员审核通过后即可登录'],
    ['rejected', '注册申请未通过', '已驳回', '如对结果有疑问，请联系管理员'],
    ['disabled', '账号已停用', '已停用', '已有数据会保留'],
    ['approved', '账号已通过审核', '已通过', '现在可以登录了'],
  ])('%s 展示用户名、状态及下一步说明，并可返回登录', async (status, title, label, description) => {
    renderAt(`?status=${status}&username=demo_user`);
    expect(screen.getByText(title)).toBeInTheDocument();
    expect(screen.getByText('demo_user')).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`状态：${label}`))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(description))).toBeInTheDocument();
    expect(screen.queryByText(/原因：/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('link', { name: '返回登录' }));
    expect(await screen.findByRole('heading', { name: '登录页面' })).toBeInTheDocument();
  });

  it.each([
    ['', '账号正在审核中'],
    ['?status=unknown', '未知'],
  ])('账号状态 %s 显示标题「%s」', (search, title) => {
    renderAt(search);
    expect(screen.getByText(title, { exact: true, selector: '.ant-result-title' })).toBeInTheDocument();
    expect(screen.queryByText(/用户名：/)).not.toBeInTheDocument();
    expect(screen.queryByText(/原因：/)).not.toBeInTheDocument();
  });

  it('仅显示导航状态携带的审核原因，不采信 URL 中的原因', () => {
    renderAt('?status=rejected&reason=URL中的原因', { reason: '请补充申请用途' });
    expect(screen.getByText('原因：请补充申请用途')).toBeInTheDocument();
    expect(screen.queryByText(/URL中的原因/)).not.toBeInTheDocument();
  });

  it('直接打开页面没有导航原因时不显示原因栏', () => {
    renderAt('?status=rejected&reason=URL中的原因', { reason: null });
    expect(screen.getByText('注册申请未通过')).toBeInTheDocument();
    expect(screen.queryByText(/原因：/)).not.toBeInTheDocument();
  });
});
