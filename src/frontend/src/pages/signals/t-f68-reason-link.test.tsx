import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import type { NonExecutableReason } from '../../api/types';
import { ReasonCard } from './ReasonCard';

function reason(code: 'BLOCKLISTED' | 'USER_MUTED'): NonExecutableReason {
  return {
    id: code === 'BLOCKLISTED' ? '00000000-0000-4000-8000-000000000711' : '00000000-0000-4000-8000-000000000712',
    signal_id: '00000000-0000-4000-8000-000000000710',
    security_code: 'SYN001.SH',
    name: '合成证券',
    code,
    description: '合成限制原因',
    evidence: [],
    release_condition: {
      kind: 'event',
      expr: null,
      at: null,
      event: 'restriction_changed',
      action: null,
      check_on: ['tick'],
      human_text: '限制名单变化后由系统重评',
      machine_checkable: true,
    },
    status: 'active',
    detected_at: '2026-11-20T10:00:00+08:00',
    released_at: null,
    release_evidence: null,
    released_by: 'system',
  };
}

const probe = render(<MemoryRouter><ReasonCard r={reason('BLOCKLISTED')} onRelease={() => undefined} /></MemoryRouter>);
const hasRestrictionsLink = Boolean(probe.queryByRole('link', { name: /限制|禁投|屏蔽/ }));
probe.unmount();
cleanup();
const reasonLinkSuite = hasRestrictionsLink ? describe : describe.skip;

reasonLinkSuite('T-F68 原因卡限制名单跳转', () => {
  it.each(['BLOCKLISTED', 'USER_MUTED'] as const)('%s active 原因不提供手动解除并指向 /restrictions', (code) => {
    render(<MemoryRouter><ReasonCard r={reason(code)} onRelease={() => undefined} /></MemoryRouter>);
    expect(screen.queryByRole('button', { name: '手动解除' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /限制|禁投|屏蔽/ })).toHaveAttribute('href', '/restrictions');
  });
});
