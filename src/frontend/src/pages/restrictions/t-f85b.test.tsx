import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { MemoryRouter } from 'react-router';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { REASONS } from '../../mocks/fixtures';
import { server } from '../../mocks/server';
import { RestrictionsPage } from './RestrictionsPage';

const API = '/api/v1';
const cooldownReason = REASONS.find((reason) => reason.code === 'SAME_TEMPLATE_COOLDOWN')!;

function renderPage() {
  render(<AppProviders client={makeQueryClient(true)}><MemoryRouter><RestrictionsPage /></MemoryRouter></AppProviders>);
}

describe('T-F85b 同模板同证券冷却', () => {
  it('冷却窗口内显示原因码中文标签和完整解除条件', async () => {
    server.use(http.get(`${API}/non-executable-reasons`, () => HttpResponse.json({ items: [cooldownReason], next_cursor: null })));
    renderPage();

    const card = await screen.findByTestId(`same-template-cooldown-${cooldownReason.id}`);
    expect(card).toHaveTextContent('同模板同证券冷却');
    expect(card).toHaveTextContent('同模板同证券冷却至到期交易日15:00（北京时间）');
    expect(card).toHaveTextContent('到点');
    expect(card).toHaveTextContent('系统自动检查');
    expect(screen.getByTestId(`same-template-release-${cooldownReason.id}`)).toHaveTextContent('2026-11-05 15:00');
    expect(cooldownReason.release_condition).toEqual({
      kind: 'time', expr: null, at: '2026-11-05T15:00:00+08:00', event: null, action: null,
      check_on: ['schedule'], human_text: '同模板同证券冷却至到期交易日15:00（北京时间）', machine_checkable: true,
    });
  });

  it('到期后夹具不返回该原因，页面不再以该原因为阻断', async () => {
    server.use(http.get(`${API}/non-executable-reasons`, () => HttpResponse.json({ items: [], next_cursor: null })));
    renderPage();
    expect(await screen.findByTestId('restrictions-page')).toBeInTheDocument();
    expect(screen.queryByTestId('same-template-cooldown-reasons')).not.toBeInTheDocument();
    expect(screen.queryByText('同模板同证券冷却')).not.toBeInTheDocument();
  });

});
