/**
 * 页面验证脚本：1440 / 1024 / 390 三种宽度逐页检查渲染、控制台错误与横向溢出，并截图。
 * 运行：node scripts/verify.mjs （需先启动 npm run dev）
 */
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';

const BASE = process.env.CI_WEB_BASE ?? 'http://localhost:5173';
const EXE =
  process.env.CI_CHROME ??
  'C:/Users/37859/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe';
const OUT = path.resolve('screenshots');

const WIDTHS = [1440, 1024, 390];

const PAGES = [
  { name: 'onboarding', url: '/onboarding', marker: '三步完成第一场模拟面试' },
  { name: 'overview', url: '/', marker: '下个练习重点', onboard: true },
  { name: 'resumes', url: '/resumes', marker: '候选人简历' },
  { name: 'resume-detail', url: '/resumes/res_demo_go_01', marker: '保存为候选人画像' },
  { name: 'jobs', url: '/jobs', marker: '目标岗位 JD' },
  { name: 'job-detail', url: '/jobs/job_demo_go_mid', marker: '简历覆盖情况' },
  { name: 'configure', url: '/configure', marker: '配置本场模拟面试' },
  { name: 'records', url: '/records', marker: '历次模拟面试' },
  { name: 'session', url: '/session/ses_demo_active_01', marker: '你的回答' },
  { name: 'report', url: '/report/ses_demo_completed_01', marker: '能力差距报告' },
];

fs.mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const results = [];
const consoleErrors = [];

for (const pageSpec of PAGES) {
  for (const width of WIDTHS) {
    const ctx = await browser.newContext({
      viewport: { width, height: 900 },
      deviceScaleFactor: 1,
    });
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') errors.push(`console: ${msg.text().slice(0, 200)}`);
    });
    page.on('pageerror', (err) => errors.push(`pageerror: ${String(err).slice(0, 200)}`));

    let ok = true;
    let reason = '';
    try {
      await page.goto(`${BASE}${pageSpec.url}`, { waitUntil: 'domcontentloaded' });
      if (pageSpec.onboard) {
        await page.evaluate(() => {
          const key = 'cs_interview_agent_db_v2';
          const db = JSON.parse(localStorage.getItem(key));
          db.onboarded = true;
          localStorage.setItem(key, JSON.stringify(db));
        });
        await page.goto(`${BASE}${pageSpec.url}`, { waitUntil: 'domcontentloaded' });
      }
      // 等待预期内容渲染
      await page.waitForSelector(`text=${pageSpec.marker}`, { timeout: 20000 });
      await page.waitForTimeout(1200);
      const overflow = await page.evaluate(() => {
        const doc = document.documentElement;
        return { scrollW: doc.scrollWidth, innerW: window.innerWidth };
      });
      if (overflow.scrollW > overflow.innerW + 2) {
        ok = false;
        reason = `横向溢出 ${overflow.scrollW} > ${overflow.innerW}`;
      }
      await page.screenshot({ path: path.join(OUT, `${pageSpec.name}-${width}.png`), fullPage: true });
      if (errors.length > 0) {
        ok = false;
        reason = errors.join(' | ');
      }
    } catch (err) {
      ok = false;
      reason = String(err).slice(0, 200);
    }
    results.push({ page: pageSpec.name, width, ok, reason });
    if (errors.length > 0) consoleErrors.push(`${pageSpec.name}@${width}: ${errors.join(' | ')}`);
    await ctx.close();
  }
}

await browser.close();

let failed = 0;
for (const r of results) {
  const status = r.ok ? 'PASS' : 'FAIL';
  if (!r.ok) failed += 1;
  console.log(`[${status}] ${r.page.padEnd(12)} ${String(r.width).padStart(4)}px  ${r.reason ?? ''}`);
}
console.log(`\n${results.length - failed}/${results.length} 通过`);
if (consoleErrors.length) {
  console.log('\n-- 控制台错误 --');
  console.log(consoleErrors.join('\n'));
}
process.exit(failed ? 1 : 0);
