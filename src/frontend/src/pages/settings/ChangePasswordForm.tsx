import { useState } from 'react';
import { Alert, Button, Form, Input } from 'antd';
import { useChangePassword } from '../../api/accountQueries';
import { ApiError } from '../../api/client';
import { PASSWORD_RULES } from '../../lib/passwordRules';

interface PasswordValues { old_password: string; new_password: string; confirm_password: string }

const ERROR_TEXT = {
  VALIDATION_ERROR: '密码信息未通过校验，请检查后重试',
  AUTH_REQUIRED: '登录已过期，请重新登录',
  ACCOUNT_NOT_APPROVED: '账号尚未通过审核或已停用',
  CSRF_FAILED: '页面已过期，请刷新页面后重试',
  RATE_LIMITED: '操作过于频繁，请稍后重试',
};
const UNKNOWN_ERROR = '修改密码失败（未知错误），请稍后重试';
const NETWORK_ERROR = '网络连接失败，请检查网络或稍后重试';
const NEW_PASSWORD_ISSUES = {
  'must be at least 10 characters': '至少 10 位',
  'must be at most 128 characters': '不超过 128 位',
  'must contain both letters and digits': '需同时包含字母和数字',
  'must not equal username': '新密码不得与用户名相同',
  'too common': '新密码过于常见，请更换',
  'must differ from old_password': '新密码不得与当前密码相同',
};

/** 按字段合并多条问题，只使用自有属性与 issue 白名单，不回显服务端原文。 */
function passwordFieldErrors(error: unknown) {
  if (!(error instanceof ApiError) || error.code !== 'VALIDATION_ERROR') return [];
  const details = error.details;
  const entries: unknown[] = Array.isArray(details?.fields) ? [...details.fields] : [];
  // 兼容已有接口的单字段错误格式。
  if (details && Object.hasOwn(details, 'field')) entries.push({ field: details.field });
  const errors: Record<'old_password' | 'new_password', string[]> = { old_password: [], new_password: [] };
  for (const entry of entries) {
    if (typeof entry !== 'object' || entry === null || !Object.hasOwn(entry, 'field')) continue;
    const { field, issue } = entry as { field: unknown; issue?: unknown };
    if (field === 'old_password') errors.old_password.push('当前密码不正确，请重新输入');
    if (field === 'new_password') {
      errors.new_password.push(Object.hasOwn(entry, 'issue') && typeof issue === 'string' && Object.hasOwn(NEW_PASSWORD_ISSUES, issue)
        ? NEW_PASSWORD_ISSUES[issue as keyof typeof NEW_PASSWORD_ISSUES] : '新密码未通过校验');
    }
  }
  return (['old_password', 'new_password'] as const)
    .filter((name) => errors[name].length)
    .map((name) => ({ name, errors: [...new Set(errors[name])] }));
}

/** 契约 §7.1、§2：只识别已知字段，不显示服务端原始消息或输入值。 */
function passwordError(error: unknown): string {
  if (!(error instanceof ApiError)) return UNKNOWN_ERROR;
  if (error.code === 'NETWORK_ERROR' || error.status === 0) return NETWORK_ERROR;
  return Object.hasOwn(ERROR_TEXT, error.code) ? ERROR_TEXT[error.code as keyof typeof ERROR_TEXT] : UNKNOWN_ERROR;
}

/** 设置页改密：复用已有变更，204 后由其清除内存兜底，后续写请求从 Cookie 重读 CSRF。 */
export function ChangePasswordForm() {
  const change = useChangePassword();
  const [form] = Form.useForm<PasswordValues>();
  const [result, setResult] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const onFinish = ({ old_password, new_password }: PasswordValues) => {
    if (change.isPending) return;
    setResult(null);
    change.mutate({ old_password, new_password }, {
      onSuccess: () => {
        form.resetFields();
        setResult({ type: 'success', text: '密码修改成功，其他会话已注销，当前会话已更新' });
      },
      onError: (error) => {
        const fields = passwordFieldErrors(error);
        if (fields.length) form.setFields(fields);
        else setResult({ type: 'error', text: passwordError(error) });
      },
    });
  };

  return (
    <section aria-labelledby="change-password-title" style={{ marginTop: 32 }}>
      <h2 id="change-password-title">修改密码</h2>
      <p className="muted">修改成功后将注销其他会话，当前会话继续使用。</p>
      {result ? <Alert type={result.type} showIcon title={result.text} role="status" style={{ margin: '12px 0' }} /> : null}
      <Form<PasswordValues> name="change-password" form={form} layout="vertical" requiredMark={false}
        disabled={change.isPending} onFinish={onFinish} onValuesChange={() => setResult(null)}>
        <Form.Item name="old_password" label="当前密码" rules={[{ required: true, whitespace: true, message: '请输入当前密码' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        <Form.Item name="new_password" label="新密码" dependencies={['old_password']} validateFirst
          extra="10–128 位，包含字母和数字，且与当前密码不同"
          rules={[
            { required: true, whitespace: true, message: '请输入新密码' },
            ...PASSWORD_RULES,
            ({ getFieldValue }) => ({
              validator: (_, value: string | undefined) => !value || value !== getFieldValue('old_password')
                ? Promise.resolve() : Promise.reject(new Error('新密码不得与当前密码相同')),
            }),
          ]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="confirm_password" label="确认新密码" dependencies={['new_password']} validateFirst
          rules={[
            { required: true, whitespace: true, message: '请再次输入新密码' },
            ({ getFieldValue }) => ({
              validator: (_, value: string | undefined) => !value || value === getFieldValue('new_password')
                ? Promise.resolve() : Promise.reject(new Error('两次输入的新密码不一致')),
            }),
          ]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={change.isPending} disabled={change.isPending}>修改密码</Button>
      </Form>
    </section>
  );
}
