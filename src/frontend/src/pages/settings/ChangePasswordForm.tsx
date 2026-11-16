import { useState } from 'react';
import { Alert, Button, Form, Input } from 'antd';
import { useChangePassword } from '../../api/accountQueries';
import { ApiError } from '../../api/client';

interface PasswordValues { old_password: string; new_password: string; confirm_password: string }

const ERROR_TEXT = {
  VALIDATION_ERROR: '密码信息未通过校验，请检查后重试',
  AUTH_REQUIRED: '登录已过期，请重新登录',
  ACCOUNT_NOT_APPROVED: '账号尚未通过审核或已停用',
  CSRF_FAILED: '页面已过期，请刷新页面后重试',
  RATE_LIMITED: '操作过于频繁，请稍后重试',
};
const UNKNOWN_ERROR = '修改密码失败（未知错误），请稍后重试';

/** 契约 §7.1、§2：只识别已知字段，不显示服务端原始消息或输入值。 */
function passwordError(error: unknown): string {
  if (!(error instanceof ApiError)) return UNKNOWN_ERROR;
  if (error.code === 'VALIDATION_ERROR') {
    const fields = error.details?.fields;
    const hasField = (field: string) => error.details?.field === field || (Array.isArray(fields)
      && fields.some((entry: unknown) => typeof entry === 'object' && entry !== null
        && Object.hasOwn(entry, 'field') && (entry as { field: unknown }).field === field));
    if (hasField('old_password')) return '当前密码不正确，请重新输入';
    if (hasField('new_password')) return '新密码未通过校验，请重新输入';
  }
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
      onError: (error) => setResult({ type: 'error', text: passwordError(error) }),
    });
  };

  return (
    <section aria-labelledby="change-password-title" style={{ marginTop: 32 }}>
      <h2 id="change-password-title">修改密码</h2>
      <p className="muted">修改成功后将注销其他会话，当前会话继续使用。</p>
      {result ? <Alert type={result.type} showIcon title={result.text} role="status" style={{ margin: '12px 0' }} /> : null}
      <Form<PasswordValues> name="change-password" form={form} layout="vertical" requiredMark={false}
        disabled={change.isPending} onFinish={onFinish} onValuesChange={() => setResult(null)}>
        <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
          <Input.Password autoComplete="current-password" />
        </Form.Item>
        {/* 契约未明确改密的长度规则，不将注册接口的规则擅自用于此处；见 T-F60 报告。 */}
        <Form.Item name="new_password" label="新密码" rules={[{ required: true, message: '请输入新密码' }]}>
          <Input.Password autoComplete="new-password" />
        </Form.Item>
        <Form.Item name="confirm_password" label="确认新密码" dependencies={['new_password']}
          rules={[
            { required: true, message: '请再次输入新密码' },
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
