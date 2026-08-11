/**
 * 交互验证：报告矩阵展开 / 逐题溯源 / 表单草稿自动保存与恢复。
 * 运行：node scripts/verify-interact.mjs （需先启动 npm run dev）
 */
import { chromium } from 'playwright-core';

const BASE = process.env.CI_WEB_BASE ?? 'http://localhost:5173';
const EXE =
  process.env.CI_CHROME ??
  'C:/Users/37859/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe';

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on('pageerror', (err) => errors.push(String(err).slice(0, 160)));

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok });
  console.log(`[${ok ? 'PASS' : 'FAIL'}] ${name}${detail ? `  ${detail}` : ''}`);
};

try {
  // 1. 报告矩阵展开
  await page.goto(`${BASE}/report/ses_demo_completed_01`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('text=JD 能力验证矩阵', { timeout: 20000 });
  const firstRow = page.locator('tr[role="button"]').first();
  await firstRow.click();
  await page.waitForSelector('text=能力结论', { timeout: 8000 });
  check('JD 验证矩阵行展开并显示溯源链', true);

  // 2. 逐题展开 + 证据溯源
  const roundQuestion = page.locator('button', { hasText: '请描述 Go 的 GMP 调度模型' }).first();
  await roundQuestion.click();
  await page.waitForSelector('text=面试官追问', { timeout: 8000 });
  await page.getByRole('button', { name: /证据溯源/ }).first().click();
  await page.waitForSelector('text=回答证据', { timeout: 8000 });
  check('逐题评估可展开，证据溯源链可见', true);

  // 3. 表单草稿自动保存与恢复
  await page.goto(`${BASE}/configure`, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#configure-role', { timeout: 15000 });
  await page.fill('#configure-role', '草稿恢复测试岗位');
  await page.waitForTimeout(1200); // 等待防抖写入
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#configure-role', { timeout: 15000 });
  const restored = await page.inputValue('#configure-role');
  check('配置表单草稿在刷新后恢复', restored === '草稿恢复测试岗位', `value="${restored}"`);

  // 4. 无简历/JD 时开始按钮禁用
  const startDisabled = await page.getByRole('button', { name: '开始模拟面试' }).isDisabled();
  check('未选择简历+JD 时「开始模拟面试」禁用', startDisabled);
} catch (err) {
  check('交互验证异常', false, String(err).slice(0, 200));
}

if (errors.length) console.log('\n-- 页面错误 --\n' + errors.join('\n'));
await browser.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} 通过`);
process.exit(failed ? 1 : 0);
