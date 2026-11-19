import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { Button, Form } from 'antd';
import { MemoryRouter, Route, Routes } from 'react-router';
import { ApiError } from '../../api/client';
import { CandidateWriteError, ConditionsEditor } from './candidateForm';

function ConditionsForm({ onSave = vi.fn(), count = 0 }: { onSave?: () => void; count?: number }) {
  const [form] = Form.useForm();
  return <Form form={form} onFinish={onSave} initialValues={{ conditions_to_hold: Array.from({ length: count }, () => ({})) }}>
    <ConditionsEditor form={form} />
    <Button htmlType="submit">保存条件</Button>
  </Form>;
}

it('添加、填写并删除成立条件，编号和计数随之更新', () => {
  render(<ConditionsForm />);
  fireEvent.click(screen.getByRole('button', { name: '添加成立条件（0/10）' }));
  fireEvent.change(screen.getByLabelText('成立条件 1（假设）'), { target: { value: '毛利率不再下降' } });
  fireEvent.click(screen.getByRole('button', { name: '添加成立条件（1/10）' }));
  expect(screen.getByLabelText('成立条件 2（假设）')).toBeInTheDocument();
  fireEvent.click(screen.getAllByRole('button', { name: '删除' })[1]);
  expect(screen.queryByLabelText('成立条件 2（假设）')).not.toBeInTheDocument();
  expect(screen.getByLabelText('成立条件 1（假设）')).toHaveValue('毛利率不再下降');
  fireEvent.click(screen.getByRole('button', { name: '删除' }));
  expect(screen.getByRole('button', { name: '添加成立条件（0/10）' })).toBeEnabled();
});

it('最多十条成立条件，删除后可以继续添加', () => {
  render(<ConditionsForm count={10} />);
  expect(screen.getByRole('button', { name: '添加成立条件（10/10）' })).toBeDisabled();
  fireEvent.click(screen.getAllByRole('button', { name: '删除' })[0]);
  fireEvent.click(screen.getByRole('button', { name: '添加成立条件（9/10）' }));
  expect(screen.getByRole('button', { name: '添加成立条件（10/10）' })).toBeDisabled();
});

it.each(['验证日期', '验证方式'])('缺少验证依据阻止保存，填写%s后可保存', async (label) => {
  const save = vi.fn();
  render(<ConditionsForm onSave={save} count={1} />);
  fireEvent.click(screen.getByRole('button', { name: '保存条件' }));
  expect(await screen.findByText('请填写条件')).toBeInTheDocument();
  expect(await screen.findByText('验证日期与验证方式至少填一项')).toBeInTheDocument();
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText('成立条件 1（假设）'), { target: { value: '毛利率不再下降' } });
  fireEvent.change(screen.getByLabelText(label), { target: { value: label === '验证日期' ? '2026-12-01' : '查看季报' } });
  fireEvent.click(screen.getByRole('button', { name: '保存条件' }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(screen.queryByText('验证日期与验证方式至少填一项')).not.toBeInTheDocument());
});

function renderError(error: unknown, onReload?: () => void) {
  return render(<MemoryRouter><Routes>
    <Route path="/" element={<CandidateWriteError error={error} onReload={onReload} />} />
    <Route path="/candidates/:id" element={<h2>已有研究候选</h2>} />
  </Routes></MemoryRouter>);
}

const apiError = (code: string, details: Record<string, unknown> | null = null) =>
  new ApiError(409, code, '保存失败', details, 'test-candidate');

it('重复候选错误提供可用的已有候选链接', async () => {
  renderError(apiError('CONFLICT', { existing_id: 'existing' }));
  expect(screen.getByRole('alert')).toHaveTextContent('该证券已有进行中的研究候选');
  fireEvent.click(screen.getByRole('link', { name: '查看已有候选' }));
  expect(await screen.findByRole('heading', { name: '已有研究候选' })).toBeInTheDocument();
});

it('版本冲突显示最新版本，点击载入最新版本调用重载', () => {
  const reload = vi.fn();
  renderError(apiError('VERSION_CONFLICT', { current_version_no: 4 }), reload);
  expect(screen.getByRole('alert')).toHaveTextContent('已有更新的第 4 版');
  expect(screen.getByRole('alert')).toHaveTextContent('本次未保存');
  fireEvent.click(screen.getByRole('button', { name: '载入最新版本' }));
  expect(reload).toHaveBeenCalledTimes(1);
});

it('版本号缺失且没有重载操作时显示提示', () => {
  renderError(apiError('VERSION_CONFLICT'));
  expect(screen.getByRole('alert')).toHaveTextContent('第 ? 版');
  expect(screen.queryByRole('button')).not.toBeInTheDocument();
});

it.each([
  [{ from: 'dropped' }, '研究候选已是“已放弃”'],
  [{ from: 'unknown' }, '研究候选已结束'],
  [null, '研究候选已结束'],
])('终态错误解释不能再建版本：%j', (details, text) => {
  renderError(apiError('INVALID_STATE_TRANSITION', details));
  expect(screen.getByRole('alert')).toHaveTextContent(text);
  expect(screen.getByRole('alert')).toHaveTextContent('需要重新研究请新建候选');
});

it('字段校验错误由表单承接，不重复显示通用错误', () => {
  renderError(apiError('VALIDATION_ERROR'));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it.each([
  [apiError('CONFLICT'), '数据冲突，请刷新后重试'],
  [new Error('保存连接中断'), '保存连接中断'],
])('其他错误展示通用说明：%s', (error, text) => {
  renderError(error);
  expect(screen.getByRole('alert')).toHaveTextContent(text);
});
