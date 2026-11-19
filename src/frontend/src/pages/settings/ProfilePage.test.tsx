import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { AppProviders } from '../../app/AppProviders';
import { makeQueryClient } from '../../app/queryClient';
import { EXPERIENCE } from '../../i18n/accountLabels';
import { server } from '../../mocks/server';
import { ProfilePage } from './ProfilePage';

const { hintOverride } = vi.hoisted(() => ({ hintOverride: { enabled: false, value: undefined as string | null | undefined } }));
// 仍是合法 novice 选项，仅模拟可选描述为空，避免将缺描述混同为未知键。
vi.mock('../../i18n/accountLabels', async (importOriginal) => {
  const original = await importOriginal<typeof import('../../i18n/accountLabels')>();
  return { ...original, EXPERIENCE: { ...original.EXPERIENCE, novice: {
    ...original.EXPERIENCE.novice,
    get hint() { return hintOverride.enabled ? hintOverride.value : original.EXPERIENCE.novice.hint; },
  } } };
});

beforeEach(() => { hintOverride.enabled = false; });

async function renderProfile(experience: string | null | undefined, exists = true) {
  server.use(http.get('/api/v1/me/profile', () => exists
    ? HttpResponse.json({ horizon_pref: ['swing'], effort: null, risk_tolerance: null, experience, max_single_position_pct: '20', version_no: 1 })
    : HttpResponse.json({ error: { code: 'NOT_FOUND', message: '尚未填写', details: null } }, { status: 404 })));
  const view = render(<AppProviders client={makeQueryClient(true)}><ProfilePage /></AppProviders>);
  await screen.findByTestId('profile-page');
  const hint = view.container.querySelector('.form-hint');
  expect(hint).not.toBeNull();
  return hint!;
}

it('没有画像时默认不填写，经验提示为空', async () => {
  const hint = await renderProfile(null, false);
  expect(within(screen.getByTestId('profile-experience')).getByRole('radio', { name: '不填写' })).toBeChecked();
  expect(hint).toBeEmptyDOMElement();
});

it.each([null, undefined])('画像经验 %s 回填为不填写，提示为空', async (experience) => {
  const hint = await renderProfile(experience);
  expect(within(screen.getByTestId('profile-experience')).getByRole('radio', { name: '不填写' })).toBeChecked();
  expect(hint).toBeEmptyDOMElement();
});

it.each(['novice', 'intermediate', 'advanced'] as const)('已知经验 %s 保留原提示', async (experience) => {
  const hint = await renderProfile(experience);
  expect(hint).toHaveTextContent(EXPERIENCE[experience].hint);
});

it('选择经验后切回不填写会清空提示，保存仍提交 null', async () => {
  let saved: unknown;
  server.use(http.put('/api/v1/me/profile', async ({ request }) => {
    saved = await request.json();
    return HttpResponse.json({ ...(saved as object), version_no: 2 });
  }));
  const hint = await renderProfile(null);
  const radios = within(screen.getByTestId('profile-experience'));
  fireEvent.click(radios.getByRole('radio', { name: '新手' }));
  expect(hint).toHaveTextContent(EXPERIENCE.novice.hint);
  fireEvent.click(radios.getByRole('radio', { name: '不填写' }));
  expect(hint).toBeEmptyDOMElement();
  fireEvent.click(screen.getByRole('button', { name: '保存为新版本' }));
  await waitFor(() => expect(saved).toMatchObject({ experience: null }));
});

it.each(['', null, undefined])('合法选项的 hint 为 %s 时不显示未知', async (hintValue) => {
  hintOverride.enabled = true;
  hintOverride.value = hintValue;
  const hint = await renderProfile('novice');
  expect(within(screen.getByTestId('profile-experience')).getByRole('radio', { name: '新手' })).toBeChecked();
  expect(hint).toBeEmptyDOMElement();
});

it.each(['future_experience', '__proto__', 'constructor', 'toString'])('未知经验 %s 安全显示未知，切回不填写可清空', async (experience) => {
  const hint = await renderProfile(experience);
  expect(hint).toHaveTextContent(/^未知$/);
  fireEvent.click(within(screen.getByTestId('profile-experience')).getByRole('radio', { name: '不填写' }));
  expect(hint).toBeEmptyDOMElement();
});
