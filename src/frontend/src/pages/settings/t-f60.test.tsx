import { QueryClient } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AppProviders } from '../../app/AppProviders';
import { apiPost, setCsrfToken } from '../../api/client';
import { server } from '../../mocks/server';
import { state } from '../../mocks/session';
import { csrfFromCookie } from '../../test/apiFetch';
import { ProfilePage } from './ProfilePage';

const API = '/api/v1';
// 仅为本地示例表单数据，不连接真实账号。
const OLD_PASSWORD = '示例旧密码Abc12345';
const NEW_PASSWORD = '示例新密码Def67890';
let client: QueryClient;

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
});
afterEach(() => {
  client.clear();
  setCsrfToken(null);
  vi.restoreAllMocks();
});

async function openForm() {
  render(<AppProviders client={client}><ProfilePage /></AppProviders>);
  return within(await screen.findByRole('region', { name: '修改密码' }));
}

type PasswordForm = Awaited<ReturnType<typeof openForm>>;
function fill(form: PasswordForm, oldPassword = OLD_PASSWORD, newPassword = NEW_PASSWORD, confirmation = newPassword) {
  fireEvent.change(form.getByLabelText('当前密码'), { target: { value: oldPassword } });
  fireEvent.change(form.getByLabelText('新密码', { exact: true }), { target: { value: newPassword } });
  fireEvent.change(form.getByLabelText('确认新密码'), { target: { value: confirmation } });
}
function submit(form: PasswordForm) {
  fireEvent.click(form.getByRole('button', { name: '修改密码' }));
}
function expectPasswordsRetained(form: PasswordForm) {
  expect(form.getByLabelText('当前密码')).toHaveValue(OLD_PASSWORD);
  expect(form.getByLabelText('新密码', { exact: true })).toHaveValue(NEW_PASSWORD);
  expect(form.getByLabelText('确认新密码')).toHaveValue(NEW_PASSWORD);
}
function fieldItem(form: PasswordForm, label: string) {
  return within(form.getByLabelText(label, { exact: true }).closest('.ant-form-item')! as HTMLElement);
}

describe('T-F60 设置页修改密码', () => {
  it('三个输入均为密码框，必填校验阻止发送请求', async () => {
    const send = vi.fn(() => new HttpResponse(null, { status: 204 }));
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    for (const label of ['当前密码', '新密码', '确认新密码']) {
      expect(form.getByLabelText(label, { exact: true })).toHaveAttribute('type', 'password');
      expect(form.getByLabelText(label, { exact: true })).toHaveAttribute('autocomplete', label === '当前密码' ? 'current-password' : 'new-password');
    }
    submit(form);
    expect(await form.findByText('请输入当前密码')).toBeInTheDocument();
    expect(await form.findByText('请输入新密码')).toBeInTheDocument();
    expect(await form.findByText('请再次输入新密码')).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
  });

  it.each([
    ['当前密码', '请输入当前密码'],
    ['新密码', '请输入新密码'],
    ['确认新密码', '请再次输入新密码'],
    ['三项', '请输入当前密码'],
  ])('%s 只有空格时显示必填提示且不发送', async (label, message) => {
    const send = vi.fn(() => new HttpResponse(null, { status: 204 }));
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    fill(form);
    for (const item of label === '三项' ? ['当前密码', '新密码', '确认新密码'] : [label]) {
      fireEvent.change(form.getByLabelText(item, { exact: true }), { target: { value: '          ' } });
    }
    submit(form);
    expect(await form.findByText(message)).toBeInTheDocument();
    if (label === '三项') {
      expect(await form.findByText('请输入新密码')).toBeInTheDocument();
      expect(await form.findByText('请再次输入新密码')).toBeInTheDocument();
    }
    expect(send).not.toHaveBeenCalled();
  });

  it.each([
    ['Ab' + '1'.repeat(7), '至少 10 位'],
    ['Ab' + '1'.repeat(127), '不超过 128 位'],
    ['示例没有字母123456', '需同时包含字母和数字'],
    ['ExampleLettersOnly', '需同时包含字母和数字'],
    ['ExampleDigits１２３', '需同时包含字母和数字'],
    [OLD_PASSWORD, '新密码不得与当前密码相同'],
  ])('拦截不符合本地规则的新密码（示例）%s', async (password, message) => {
    const send = vi.fn(() => new HttpResponse(null, { status: 204 }));
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    fill(form, OLD_PASSWORD, password);
    submit(form);
    expect(await fieldItem(form, '新密码').findByText(message)).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
  });

  it.each([10, 128])('新密码恰为 %s 字符可提交且不裁剪原值', async (length) => {
    const password = 'Ab' + '1'.repeat(length - 3) + ' ';
    const send = vi.fn(async ({ request }: { request: Request }) => {
      expect(await request.json()).toEqual({ old_password: OLD_PASSWORD, new_password: password });
      return new HttpResponse(null, { status: 204 });
    });
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    fill(form, OLD_PASSWORD, password);
    submit(form);
    expect(await form.findByRole('status')).toHaveTextContent('密码修改成功');
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('修改当前密码后重校验新旧密码是否相同', async () => {
    const send = vi.fn(() => new HttpResponse(null, { status: 204 }));
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    fill(form, OLD_PASSWORD, OLD_PASSWORD);
    submit(form);
    expect(await form.findByText('新密码不得与当前密码相同')).toBeInTheDocument();
    fireEvent.change(form.getByLabelText('当前密码'), { target: { value: NEW_PASSWORD } });
    await waitFor(() => expect(form.queryByText('新密码不得与当前密码相同')).not.toBeInTheDocument());
    fireEvent.change(form.getByLabelText('当前密码'), { target: { value: OLD_PASSWORD } });
    expect(await form.findByText('新密码不得与当前密码相同')).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
  });

  it('两次新密码不一致时拦截，修改新密码后重新校验确认项', async () => {
    const send = vi.fn(() => new HttpResponse(null, { status: 204 }));
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    fill(form, OLD_PASSWORD, NEW_PASSWORD, '不一致');
    submit(form);
    expect(await form.findByText('两次输入的新密码不一致')).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
    fireEvent.change(form.getByLabelText('确认新密码'), { target: { value: NEW_PASSWORD } });
    await waitFor(() => expect(form.queryByText('两次输入的新密码不一致')).not.toBeInTheDocument());
    fireEvent.change(form.getByLabelText('新密码', { exact: true }), { target: { value: '另一新密码Ab123456' } });
    expect(await form.findByText('两次输入的新密码不一致')).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();
  });

  it('提交中禁用全部输入和按钮，仅发送契约字段，成功后清空并提示', async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => { release = resolve; });
    const send = vi.fn(async ({ request }: { request: Request }) => {
      const body: unknown = await request.json();
      await gate;
      expect(body).toEqual({ old_password: OLD_PASSWORD, new_password: NEW_PASSWORD });
      return new HttpResponse(null, { status: 204 });
    });
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    fill(form);
    submit(form);
    try {
      await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
      for (const label of ['当前密码', '新密码', '确认新密码']) {
        expect(form.getByLabelText(label, { exact: true })).toBeDisabled();
      }
      expect(form.getByRole('button', { name: /修改密码/ })).toBeDisabled();
      fireEvent.submit(form.getByLabelText('当前密码').closest('form')!);
      expect(send).toHaveBeenCalledTimes(1);
    } finally {
      release();
    }
    expect(await form.findByRole('status')).toHaveTextContent('密码修改成功，其他会话已注销，当前会话已更新');
    for (const label of ['当前密码', '新密码', '确认新密码']) {
      expect(form.getByLabelText(label, { exact: true })).toHaveValue('');
      expect(form.getByLabelText(label, { exact: true })).toBeEnabled();
    }
  });

  it('复用现有 MSW：204 后保留当前用户，后续写请求重读轮换的 Cookie 并清除旧内存兜底', async () => {
    const user = state.currentUserId;
    const oldToken = csrfFromCookie();
    setCsrfToken('示例过期内存令牌');
    const form = await openForm();
    fill(form);
    submit(form);
    expect(await form.findByRole('status')).toHaveTextContent('密码修改成功');
    expect(state.currentUserId).toBe(user);
    const token = csrfFromCookie();
    expect(token).toBeTruthy();
    expect(token).not.toBe(oldToken);
    const headers: (string | null)[] = [];
    server.use(http.post(`${API}/auth/password`, ({ request }) => {
      headers.push(request.headers.get('X-CSRF-Token'));
      return new HttpResponse(null, { status: 204 });
    }));
    await apiPost('/auth/password', { old_password: OLD_PASSWORD, new_password: NEW_PASSWORD });
    document.cookie = 'csrf_token=; Path=/; Max-Age=0';
    await apiPost('/auth/password', { old_password: OLD_PASSWORD, new_password: NEW_PASSWORD });
    expect(headers).toEqual([token, null]);
  });

  it.each(['断网', '超时'])('%s 显示网络提示并保留三个密码，不自动重试', async (kind) => {
    const send = vi.fn(() => HttpResponse.error());
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    const timeout = vi.fn<typeof fetch>();
    if (kind === '超时') {
      const originalFetch = globalThis.fetch;
      timeout.mockImplementation((input, init) => {
        if (String(input).endsWith('/auth/password')) return Promise.reject(new DOMException('示例超时', 'TimeoutError'));
        return originalFetch(input, init);
      });
      vi.spyOn(globalThis, 'fetch').mockImplementation(timeout);
    }
    fill(form);
    submit(form);
    expect(await form.findByRole('status')).toHaveTextContent('网络连接失败，请检查网络或稍后重试');
    expect(form.getByRole('status')).not.toHaveTextContent('未知错误');
    expectPasswordsRetained(form);
    expect(form.getByRole('button', { name: '修改密码' })).toBeEnabled();
    if (kind === '超时') expect(timeout.mock.calls.filter(([input]) => String(input).endsWith('/auth/password'))).toHaveLength(1);
    else expect(send).toHaveBeenCalledTimes(1);
  });

  it('服务端多条 issue 按字段全部显示中文，失败保留输入', async () => {
    const issues = [
      ['must be at least 10 characters', '至少 10 位'],
      ['must be at most 128 characters', '不超过 128 位'],
      ['must contain both letters and digits', '需同时包含字母和数字'],
      ['must not equal username', '新密码不得与用户名相同'],
      ['too common', '新密码过于常见，请更换'],
      ['must differ from old_password', '新密码不得与当前密码相同'],
    ];
    const send = vi.fn(() => HttpResponse.json({ error: {
      code: 'VALIDATION_ERROR', message: '不可回显的原始服务端消息',
      details: { fields: [{ field: 'old_password', issue: 'incorrect' }, ...issues.map(([issue]) => ({ field: 'new_password', issue }))] },
    } }, { status: 400 }));
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    fill(form);
    submit(form);
    expect(await fieldItem(form, '当前密码').findByText('当前密码不正确，请重新输入')).toBeInTheDocument();
    for (const [, text] of issues) expect(await fieldItem(form, '新密码').findByText(text)).toBeInTheDocument();
    expect(form.queryByText(/不可回显/)).not.toBeInTheDocument();
    expectPasswordsRetained(form);
    expect(send).toHaveBeenCalledTimes(1);
  });

  it.each([
    [{ field: 'old_password' }, '当前密码', '当前密码不正确，请重新输入'],
    [{ fields: [{ field: 'old_password', issue: 'incorrect' }] }, '当前密码', '当前密码不正确，请重新输入'],
    [{ fields: [{ field: 'new_password', issue: '未知问题不可回显' }] }, '新密码', '新密码未通过校验'],
    [{ fields: [{ field: 'new_password', issue: '__proto__' }] }, '新密码', '新密码未通过校验'],
    [{ fields: [{ field: 'new_password', issue: 'constructor' }] }, '新密码', '新密码未通过校验'],
    [{ fields: [{ field: 'new_password', issue: 'toString' }] }, '新密码', '新密码未通过校验'],
  ])('字段错误 %j 安全映射在对应字段', async (details, label, text) => {
    server.use(http.post(`${API}/auth/password`, () => HttpResponse.json({
      error: { code: 'VALIDATION_ERROR', message: '不可回显的原始服务端消息', details },
    }, { status: 400 })));
    const form = await openForm();
    fill(form);
    submit(form);
    expect(await fieldItem(form, label).findByText(text)).toBeInTheDocument();
    expect(form.queryByText(/不可回显/)).not.toBeInTheDocument();
    expectPasswordsRetained(form);
  });

  const errors: [number, string, Record<string, unknown> | null, string][] = [
    [400, 'VALIDATION_ERROR', null, '密码信息未通过校验，请检查后重试'],
    [401, 'AUTH_REQUIRED', null, '登录已过期，请重新登录'],
    [403, 'ACCOUNT_NOT_APPROVED', null, '账号尚未通过审核或已停用'],
    [403, 'CSRF_FAILED', null, '页面已过期，请刷新页面后重试'],
    [429, 'RATE_LIMITED', null, '操作过于频繁，请稍后重试'],
    [500, 'FUTURE_PASSWORD_ERROR', null, '修改密码失败（未知错误），请稍后重试'],
    [500, '__proto__', null, '修改密码失败（未知错误），请稍后重试'],
    [500, 'constructor', null, '修改密码失败（未知错误），请稍后重试'],
    [500, 'NETWORK_ERROR', null, '网络连接失败，请检查网络或稍后重试'],
    [400, 'VALIDATION_ERROR', { fields: [{ field: '__proto__', issue: '不可回显' }] }, '密码信息未通过校验，请检查后重试'],
    [400, 'VALIDATION_ERROR', { field: 'constructor' }, '密码信息未通过校验，请检查后重试'],
  ];
  it.each(errors)('错误 %s / %s / %j 显示中文且不自动重试', async (status, code, details, text) => {
    const send = vi.fn(() => HttpResponse.json({
      error: { code, message: '不可回显的原始服务端消息', details, request_id: '示例请求' },
    }, { status }));
    server.use(http.post(`${API}/auth/password`, send));
    const form = await openForm();
    fill(form);
    submit(form);
    expect(await form.findByRole('status')).toHaveTextContent(text);
    expect(form.queryByText(/不可回显/)).not.toBeInTheDocument();
    expect(form.getByRole('button', { name: '修改密码' })).toBeEnabled();
    expect(send).toHaveBeenCalledTimes(1);
    expectPasswordsRetained(form);
    // 开始修改后清掉旧提示，允许用户更正后再次提交。
    fireEvent.change(form.getByLabelText('当前密码'), { target: { value: '更正后的示例密码12345' } });
    expect(form.queryByRole('status')).not.toBeInTheDocument();
  });
});
