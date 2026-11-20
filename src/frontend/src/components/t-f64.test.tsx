import { fireEvent, render, screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router';
import { AppProviders } from '../app/AppProviders';
import { makeQueryClient } from '../app/queryClient';
import type { ImportBatch, ImportFinding, ImportRow } from '../api/accountTypes';
import { IMPORT_422_TEXT } from '../api/importCodes';
import { ownValue } from '../lib/enumValue';
import { server } from '../mocks/server';
import { publicBatch, state } from '../mocks/session';
import { ImportWizardPage, RowsTable } from '../pages/portfolio/ImportWizardPage';
import { ActionBadge, ConfidenceTag, ConsensusBadge, DataStatusTag, EnumTag, GapNote } from './common';

const unknowns = ['future_value', '__proto__', 'constructor', 'toString'];
const neutral = (el: HTMLElement) => {
  expect(el).toHaveTextContent('未知');
  expect(el.className).not.toMatch(/ant-tag-(?:red|green|gold|orange|blue|purple|processing|default)/);
  expect(el.style.color).toBe('');
};
function batchPage(b: ImportBatch) {
  server.use(http.get('/api/v1/imports/:id', () => HttpResponse.json(b)),
    http.get('/api/v1/imports/:id/rows', () => HttpResponse.json({ items: [], next_cursor: null })));
  const router = createMemoryRouter([{ path: '/portfolio/import/:batchId', element: <ImportWizardPage /> }], { initialEntries: [`/portfolio/import/${b.batch_id}`] });
  render(<AppProviders client={makeQueryClient(true)}><RouterProvider router={router} /></AppProviders>);
}
const batch = (extra: Partial<ImportBatch> = {}) => ({ ...publicBatch(state.batches[0]), ...extra });

it('已知键保留 null、空串、false、0、空 hint，未知键才兜底', () => {
  const map = { nil: null, empty: '', no: false, zero: 0, hint: '' };
  for (const key of Object.keys(map)) expect(ownValue(map, key, '未知')).toBe(map[key as keyof typeof map]);
  for (const key of unknowns) expect(ownValue(map, key, '未知')).toBe('未知');
  const { container } = render(<EnumTag map={{ empty: { text: '', color: undefined }, zero: { text: 0 } }} value="empty" />);
  expect(container.textContent).toBe('');
});

describe.each(unknowns)('未知键 %s', (value) => {
  it('数据状态、原因、缺口正文与置信度均安全兜底且中性', () => {
    const gaps = [{ key: 'x', reason: value, message: '缺口说明' }] as never;
    const { container } = render(<MemoryRouter>
      <DataStatusTag status={value as never} gaps={gaps} />
      <GapNote status="partial" gaps={gaps} />
      <ConfidenceTag c={{ level: value as never, value: 0 }} />
    </MemoryRouter>);
    neutral(screen.getByTestId('data-status-tag'));
    expect(container.querySelector<HTMLElement>('.dot')!.style.background).toBe('');
    expect(document.getElementById(screen.getByTestId('data-status-tag').getAttribute('aria-describedby')!)!).toHaveTextContent('x：未知 — 缺口说明');
    expect(screen.getByTestId('gap-note')).toHaveTextContent('未知（缺口说明）');
    neutral(container.querySelector('.ant-tag')!);
    expect(container.querySelector('.num')).toHaveTextContent('0.00');
  });
  it('动作的短名、全名与颜色均兜底', async () => {
    const { container } = render(<ActionBadge action={value as never} />);
    const badge = container.querySelector<HTMLElement>('.action-badge')!;
    neutral(badge);
    expect(badge.style.borderColor).toBe('');
    fireEvent.mouseEnter(badge);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('未知');
  });
  it('分歧提示中的未知动作不读取原型链', async () => {
    render(<ConsensusBadge status="divergent" actions={{ [value]: 0 }} />);
    fireEvent.mouseEnter(screen.getByText('分歧'));
    expect(await screen.findByRole('tooltip')).toHaveTextContent('未知 0');
  });
  it('批次状态和类型兜底', async () => {
    batchPage(batch({ status: value as never, kind: value as never }));
    neutral(await screen.findByTestId('batch-status'));
    expect(screen.getByTestId('import-batch')).toHaveTextContent('未知 · 上传于');
  });
  it('类型不匹配提示保留已知候选、未知上传类型兜底；列映射忽略值不变', async () => {
    const finding = { id: 'f', code: 'IMPORT_UNRECOGNIZED_FORMAT', severity: 'error', params: { candidate_ids: ['tdx_positions_v1'] }, resolution_choices: [] } as unknown as ImportFinding;
    batchPage(batch({ status: 'failed', kind: value as never, file_findings: [finding], detected_columns: [value, '空列', '未知字段'], mapping: { 空列: '', 未知字段: value } }));
    expect(await screen.findByTestId('kind-mismatch')).toHaveTextContent('本批次按“未知”上传');
    expect(screen.getByTestId('kind-reupload')).toHaveTextContent('按持仓重新上传');
    expect(screen.getByTestId(`map-${value}`)).toHaveTextContent('（忽略此列）');
    expect(screen.getByTestId('map-空列')).toHaveTextContent('（忽略此列）');
    expect(screen.getByTestId('map-未知字段')).toHaveTextContent('未知');
  });
  it('行状态、去重、方向兜底；null 去重与方向保持原显示', () => {
    const normalized = { trade_date: '2026-11-01', trade_time: null, security_code: '600000.SH', name: '示例', side: value, qty: '0', price: '0', amount: '0', biz_type_raw: '原业务' };
    const rows = [{ row_no: 1, status: value, dedup_status: value, normalized, findings: [] }, { row_no: 2, status: 'ok', dedup_status: null, normalized: { ...normalized, side: null }, findings: [] }] as unknown as ImportRow[];
    const { container } = render(<RowsTable rows={rows} />);
    const first = container.querySelector('tr[data-row-key="1"]')!;
    const tags = first.querySelectorAll<HTMLElement>('.ant-tag');
    expect(tags).toHaveLength(3);
    tags.forEach(neutral);
    const second = container.querySelector('tr[data-row-key="2"]')!;
    expect(second).toHaveTextContent('正常');
    expect(second).toHaveTextContent('原业务');
    expect(second.querySelectorAll('.ant-tag')).toHaveLength(1);
    expect(second.querySelector('td:nth-child(3)')).toHaveTextContent('—');
  });
  it('确认错误码兜底', async () => {
    server.use(http.post('/api/v1/imports/:id/confirm', () => HttpResponse.json({ error: { code: value, message: '说明', details: null, request_id: null } }, { status: 422 })));
    batchPage(batch({ status: 'previewed' }));
    fireEvent.click(await screen.findByTestId('confirm-import'));
    expect(await screen.findByTestId('confirm-error')).toHaveTextContent('未知');
  });
  it('写入完成后的未知对账结果兜底', async () => {
    server.use(http.post('/api/v1/imports/:id/confirm', () => HttpResponse.json({ status: 'committed', written: { trades: 0, events: 0, snapshot_positions: 0 }, reconciliation: { status: value, diff_count: 0 } })));
    // 实际确认钩子更新批次缓存并重新请求批次头。
    const b = batch({ status: 'previewed' });
    batchPage(b);
    fireEvent.click(await screen.findByTestId('confirm-import'));
    b.status = 'committed';
    neutral(await within(await screen.findByTestId('import-done')).findByText('未知'));
  });
});

it('已知确认错误的未知提示码显示中性未知，已知提示保留颜色', async () => {
  server.use(http.post('/api/v1/imports/:id/confirm', () => HttpResponse.json({ error: { code: 'IMPORT_WARNINGS_UNACKNOWLEDGED', message: '', details: { codes: [...unknowns, 'IMPORT_UNKNOWN_SECURITY'] }, request_id: null } }, { status: 422 })));
  batchPage(batch({ status: 'previewed' }));
  fireEvent.click(await screen.findByTestId('confirm-import'));
  const error = await screen.findByTestId('confirm-error');
  expect(error).toHaveTextContent(IMPORT_422_TEXT.IMPORT_WARNINGS_UNACKNOWLEDGED);
  within(error).getAllByText('未知').forEach(neutral);
  expect(within(error).getByText('证券不在主数据中')).toHaveClass('ant-tag-orange');
});

it('确认时批次状态冲突继续显示通用写入错误', async () => {
  server.use(http.post('/api/v1/imports/:id/confirm', () => HttpResponse.json({ error: { code: 'INVALID_STATE_TRANSITION', message: '批次状态已变更', details: null, request_id: null } }, { status: 409 })));
  batchPage(batch({ status: 'previewed' }));
  fireEvent.click(await screen.findByTestId('confirm-import'));
  const error = await within(screen.getByTestId('confirm-panel')).findByRole('alert');
  expect(error).toHaveTextContent('写入失败');
  expect(error).toHaveAttribute('data-code', 'INVALID_STATE_TRANSITION');
});
