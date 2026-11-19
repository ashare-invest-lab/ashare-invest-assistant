/**
 * 主线真数据 E2E（仅只读浏览；登录是唯一表单提交）。
 * 站点须为 replay 模式（MAIRUI_MODE=replay），不得连接真实麦蕊。
 * 用法（已启动站点，并在环境变量中提供凭据）：
 * E2E_BASE_URL=http://127.0.0.1:8080 E2E_USER=… E2E_PASS=… pnpm -C tests e2e mainline-real.spec.ts
 * 缺任一环境变量时整个 describe skip；不上传、不测试证书、不刷新行情、不同步。
 */
import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';
import type { TodayResponse } from '../../src/frontend/src/api/types';
import { requiresTodayAccount } from './mainline-real.helpers';

const enabled = Boolean(process.env.E2E_BASE_URL && process.env.E2E_USER && process.env.E2E_PASS);

// 覆盖配置中的失败采集，避免登录表单、请求体与凭据进入媒体或 trace。
test.use({ trace: 'off', screenshot: 'off', video: 'off' });

async function enterCredential(input: Locator, value: string) {
  await expect(input).toBeEditable();
  // Playwright fill 的报告步骤标题包含输入值；evaluate 的标题不包含参数。
  // 使用原生 setter 与冒泡 input 事件更新 React/Ant Design 的受控输入。
  await input.evaluate((node, text) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
    if (!setter) throw new Error('登录输入框不可用');
    setter.call(node, text);
    node.dispatchEvent(new Event('input', { bubbles: true }));
    node.dispatchEvent(new Event('change', { bubbles: true }));
  }, value);
}

async function expectHealthyPage(page: Page) {
  await expect(page.getByText('Unexpected Application Error', { exact: false })).toHaveCount(0);
  // 应用使用 RouterProvider 的默认错误边界；也拒绝被局部 API 错误替代的页面。
  await expect(page.locator('.error-box')).toHaveCount(0);
}

async function expectMarketStructure(scope: Locator) {
  // 行情允许降级，不要求价格或任何业务数值。当前 DataStatusTag 将 unavailable 显示为「不可用」。
  await expect(scope.locator('.detail-head .ds-tag').first()).toHaveText(
    /^(最新|已过期|拉取中|部分缺失|不可用|不适用)$/,
  );
  // 分时视图只在持仓行出现；无证书/缺数据时必须明确说明，不能用空白冒充行情。
  // 没有 t-view 节点（无持仓或日报页）时下方循环为空，属预期；分时空态暂无统一文案，不强造断言（架构师非阻塞项，T-F42d）。
  const unavailable = scope.locator('[data-testid^="t-view-"][data-state="unavailable"]');
  for (const cell of await unavailable.all()) {
    await expect(cell).toBeVisible();
    await expect(cell).toContainText('数据暂不可用');
  }
}

test.describe('主线真数据只读链路', () => {
  test.skip(!enabled, '须同时设置 E2E_BASE_URL、E2E_USER、E2E_PASS');
  test.describe.configure({ mode: 'serial', retries: 0, timeout: 120_000 });
  test.afterEach(async ({ page }, info) => {
    // 失败快照也不保留登录后的用户名显示。
    if (info.status !== info.expectedStatus) await page.goto('about:blank').catch(() => {});
  });

  test('登录 → 持仓 → 导入 → 今日关注 → 盘后日报', async ({ page }) => {
    await test.step('登录并进入持仓', async () => {
      await page.goto('/login?next=%2Fportfolio');
      const login = page.getByTestId('login-page');
      await expect(login).toBeVisible();
      await expectHealthyPage(page);
      try {
        await enterCredential(login.getByLabel('用户名', { exact: true }), process.env.E2E_USER!);
        await enterCredential(login.getByLabel('密码', { exact: true }), process.env.E2E_PASS!);
        // antd 会在两字中文按钮里插空格（「登 录」），按 submit 定位。
        await login.locator('button[type="submit"]').click();
        // 未审核账号也会离开 /login，须先确认真正进入受保护页面。
        await expect(page.getByTestId('portfolio-page')).toBeVisible();
      } catch {
        // 失败时清空页面，避免自动 error-context 快照保留用户名或表单内容。
        await page.goto('about:blank').catch(() => {});
        throw new Error('登录未能进入持仓页（凭据已隐藏）');
      }
      await expect(page).not.toHaveURL(/\/login(?:[/?#]|$)/);
      await expect(page).toHaveURL((url) => url.pathname === '/portfolio');
      await expectHealthyPage(page);
    });

    await test.step('持仓表或明确空态', async () => {
      const portfolio = page.getByTestId('portfolio-page');
      await expect(portfolio.getByRole('heading', { name: '持仓与账户', exact: true })).toBeVisible();
      const positions = portfolio.getByTestId('positions-tab');
      const noAccount = portfolio.getByText(
        '还没有券商账户。先新建一个账户，再导入通达信交割单或持仓快照。', { exact: true },
      );
      await expect(positions.or(noAccount)).toBeVisible();
      if (await positions.isVisible()) {
        await expect(positions.getByRole('table').or(positions.getByText('暂无持仓', { exact: true })).first()).toBeVisible();
      } else {
        await expect(noAccount).toBeVisible();
      }
      await expectHealthyPage(page);
    });

    await test.step('导入上传入口或无账户空态', async () => {
      await page.goto('/portfolio/import');
      const imports = page.getByTestId('import-upload');
      await expect(imports).toBeVisible();
      await expect(imports.getByRole('heading', { name: '交割单 / 持仓导入', exact: true })).toBeVisible();
      const upload = imports.getByText('把通达信导出的 .txt / .csv 拖到这里，或点击选择', { exact: true });
      const noAccount = imports.getByText('还没有券商账户，请先到', { exact: false });
      await expect(upload.or(noAccount)).toBeVisible();
      // 只观察入口，不点击文件选择、不填写或提交导入表单。
      await expectHealthyPage(page);
    });

    await test.step('今日关注标题及各卡片区', async () => {
      const todayResponse = page.waitForResponse((response) =>
        new URL(response.url()).pathname === '/api/v1/today'
        && response.request().method() === 'GET' && response.status() === 200,
      );
      await page.goto('/today');
      const todayData: TodayResponse = await (await todayResponse).json();
      const today = page.getByTestId('today-page');
      await expect(today).toBeVisible();
      await expect(today.getByText('今日关注', { exact: true })).toBeVisible();
      for (const id of [
        'today-daily-report', 'today-reconciliation', 'today-focus', 'today-watchlist',
        'today-drafts', 'today-risks', 'today-released', 'today-invalidations',
        'today-alerts', 'today-plan-triggers', 'today-data-gaps',
      ]) {
        await expect(today.getByTestId(id)).toBeVisible();
      }
      // 与页面共用日报请求规则：S1/S3 即便 ready、有日报链接也不渲染账户卡。
      if (requiresTodayAccount(todayData)) {
        await expect(today.getByTestId('today-account')).toBeVisible();
      } else {
        await expect(today.getByTestId('today-account')).toHaveCount(0);
      }
      await expectMarketStructure(today);
      await expectHealthyPage(page);
    });

    await test.step('盘后日报或明确空态', async () => {
      await page.goto('/daily-reports');
      const report = page.getByTestId('daily-report');
      const empty = page.getByText('暂无日报', { exact: true });
      await expect(report.or(empty)).toBeVisible();
      if (await report.isVisible()) {
        await expect(report.getByRole('heading', { name: '盘后日报', exact: true })).toBeVisible();
        for (const id of ['report-overview', 'report-context', 'report-stocks']) {
          await expect(report.locator(`#${id}`)).toBeVisible();
        }
        await expectMarketStructure(report);
      } else {
        await expect(empty).toBeVisible();
      }
      await expectHealthyPage(page);
    });
  });
});
