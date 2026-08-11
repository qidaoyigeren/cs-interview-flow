/**
 * 全流程验证：上传简历 → 保存为候选人画像 → 配置面试 → 答题推进 → 生成报告。
 * 运行：node scripts/verify-flow.mjs （需先启动 npm run dev）
 */
import { chromium } from 'playwright-core';
import path from 'node:path';

const BASE = process.env.CI_WEB_BASE ?? 'http://localhost:5173';
const EXE =
  process.env.CI_CHROME ??
  'C:/Users/37859/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe';
const OUT = path.resolve('screenshots');

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const errors = [];
page.on('console', (msg) => {
  if (msg.type() === 'error') errors.push(`console: ${msg.text().slice(0, 160)}`);
});
page.on('pageerror', (err) => errors.push(`pageerror: ${String(err).slice(0, 160)}`));

const dbRaw = () =>
  page.evaluate(() => localStorage.getItem('cs_interview_agent_db_v2'));
const db = async () => {
  const raw = await dbRaw();
  return raw ? JSON.parse(raw) : null;
};

const step = (name, fn) => {
  console.log(`— ${name}`);
  return fn();
};

let failed = false;
const fail = (reason) => {
  failed = true;
  console.log(`[FAIL] ${reason}`);
  if (errors.length) console.log('  控制台错误: ' + errors.join(' | '));
};

try {
  // 1. 上传简历
  await step('上传简历文件', async () => {
    await page.goto(`${BASE}/resumes`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('text=候选人简历', { timeout: 15000 });
    await page.locator('input[type="file"]').first().setInputFiles({
      name: '李四-Go后端-简历.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('Go 后端工程师 李四，掌握 Go/MySQL/Redis/Kafka'),
    });
    await page.waitForFunction(
      () => {
        const raw = localStorage.getItem('cs_interview_agent_db_v2');
        if (!raw) return false;
        const d = JSON.parse(raw);
        return d.resumes.some(
          (r) => r.fileName === '李四-Go后端-简历.txt' && r.parseStatus === 'parsed',
        );
      },
      { timeout: 20000 },
    );
    await page.screenshot({ path: path.join(OUT, 'flow-uploaded.png'), fullPage: true });
    console.log('  [PASS] 简历已上传并解析完成');
  });

  // 2. 进入简历详情 → 保存为候选人画像
  const resumeId = await step('保存为候选人画像', async () => {
    const id = await page.evaluate(() => {
      const raw = localStorage.getItem('cs_interview_agent_db_v2');
      const d = JSON.parse(raw);
      return d.resumes.find((r) => r.fileName === '李四-Go后端-简历.txt').id;
    });
    await page.goto(`${BASE}/resumes/${id}`, { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('text=保存为候选人画像', { timeout: 15000 });
    await page.getByRole('button', { name: '保存为候选人画像' }).click();
    await page.waitForURL(/\/configure\?resume=/, { timeout: 20000 });
    console.log('  [PASS] 画像已保存，跳转至新建面试');
    return id;
  });

  // 3. 配置面试
  await step('配置面试并开始', async () => {
    await page.waitForSelector('#configure-job', { timeout: 15000 });
    await page.selectOption('#configure-job', 'job_demo_go_mid');
    // 题目数量改为 3，缩短流程
    await page.locator('input[type="number"]').first().fill('3');
    await page.waitForTimeout(400); // 等待草稿防抖写入
    await page.screenshot({ path: path.join(OUT, 'flow-configure.png'), fullPage: true });
    await page.getByRole('button', { name: '开始模拟面试' }).click();
    await page.waitForURL(/\/session\//, { timeout: 25000 });
    console.log('  [PASS] 面试已创建并进入实时面试');
  });

  const sid = new URL(page.url()).pathname.split('/').pop();

  // 4. 第 1 题（理论）回答
  await step('第 1 题（理论）提交回答', async () => {
    await page.waitForSelector('textarea[placeholder^="尽量结构化作答"]', { timeout: 15000 });
    await page.fill(
      'textarea[placeholder^="尽量结构化作答"]',
      'GMP 模型中 G 是 goroutine，M 是线程，P 是处理器队列。调度切换发生在系统调用阻塞、channel 阻塞和抢占式调度。GOMAXPROCS 决定并行度。项目里用 goroutine 加 channel 做召回并行与结果汇总。',
    );
    await page.screenshot({ path: path.join(OUT, 'flow-session-answer.png'), fullPage: true });
    await page.getByRole('button', { name: '提交回答' }).click();
    await page.waitForFunction(
      (targetId) => {
        const raw = localStorage.getItem("cs_interview_agent_db_v2");
        if (!raw) return false;
        const d = JSON.parse(raw);
        const s = d.sessions.find((x) => x.id === targetId);
        return s && s.completedQuestionCount >= 1;
      },
      sid,
      { timeout: 20000 },
    );
    console.log('  [PASS] 回答已评估并进入下一题');
  });

  // 5. 第 2 题（算法题）提交代码
  await step('第 2 题（算法题）提交代码', async () => {
    await page.waitForSelector('.monaco-editor', { timeout: 20000 });
    await page.waitForTimeout(1500); // 等待 Monaco 初始化
    await page.getByRole('button', { name: '提交代码' }).click();
    await page.waitForFunction(
      (targetId) => {
        const raw = localStorage.getItem("cs_interview_agent_db_v2");
        if (!raw) return false;
        const d = JSON.parse(raw);
        const s = d.sessions.find((x) => x.id === targetId);
        return s && s.completedQuestionCount >= 2;
      },
      sid,
      { timeout: 20000 },
    );
    console.log('  [PASS] 代码已提交并进入下一题');
  });

  // 6. 第 3 题（理论）回答 → 完成 → 报告
  await step('第 3 题（理论）回答 → 生成报告', async () => {
    await page.waitForSelector('textarea[placeholder^="尽量结构化作答"]', { timeout: 20000 });
    await page.fill(
      'textarea[placeholder^="尽量结构化作答"]',
      '最左前缀要求查询条件从联合索引第一列开始连续匹配，跳列会导致后面的列无法走索引。覆盖索引是查询字段都在索引中，可以避免回表，减少随机 IO。建索引建议高基数列在前，避免在索引列上使用函数。',
    );
    await page.getByRole('button', { name: '提交回答' }).click();
    await page.waitForURL(/\/report\//, { timeout: 30000 });
    await page.waitForSelector('text=能力差距报告', { timeout: 15000 });
    await page.screenshot({ path: path.join(OUT, 'flow-report.png'), fullPage: true });
    console.log('  [PASS] 面试完成并生成能力差距报告');
  });
} catch (err) {
  fail(String(err).slice(0, 300));
  await page.screenshot({ path: path.join(OUT, 'flow-error.png'), fullPage: true });
}

if (errors.length) {
  console.log('\n-- 控制台错误 --');
  console.log(errors.join('\n'));
}

await browser.close();
console.log(failed ? '\n[结果] 流程验证失败' : '\n[结果] 全流程验证通过');
process.exit(failed ? 1 : 0);
