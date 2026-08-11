# CS Interview Agent · 模拟面试前端

面向求职者的计算机专业模拟面试训练产品前端。独立的 React + TypeScript + Vite 应用，
不依赖 RAGFlow 管理后台布局；复用 RAGFlow 项目中已定义的 CS Interview 类型定义
（`web/src/interfaces/database/cs-interview.ts`，只读导入，单一来源）。

## 技术栈

- React 18 · TypeScript 5.9 · Vite 7
- Tailwind CSS 3 · React Router 7 · TanStack Query 5
- Lucide Icons · Monaco Editor（算法题，离线打包，不依赖 CDN）
- 轻量 SVG 雷达图 + 纯 CSS 能力条（无图表库）

## 启动

```bash
cd cs-interview-web
npm install
npm run dev        # http://localhost:5173
```

生产构建与预览：

```bash
npm run build
npm run preview
```

## 验证命令

```bash
npm run type-check   # tsc --noEmit
npm run lint         # oxlint
npm run build        # vite build
```

浏览器级验证（需先启动 dev server）：

```bash
node scripts/verify.mjs         # 10 个页面 × 1440/1024/390 三宽度：渲染、控制台错误、横向溢出、截图
node scripts/verify-flow.mjs    # 全流程：上传简历 → 保存画像 → 配置面试 → 答题 → 生成报告
node scripts/verify-interact.mjs# 交互：报告矩阵展开 / 逐题溯源 / 表单草稿恢复
```

截图输出到 `screenshots/`。

## 数据与后端

- 后端默认不可用，因此内置 **mock service 层**（`src/lib/mock/api.ts`），
  镜像 `api/apps/restful_apis/cs_interview_api.py` 的方法语义与对象形状，
  模拟 500–900ms 网络延迟，数据持久化到 `localStorage`。
- 接入真实后端时，仅需替换 `mockApi` 实现为真实 HTTP 调用，类型与对象形状不变。
- 首次加载自动填充一套演示数据：Go 后端校招生简历、中级 Go 后端 JD、
  一场包含 8 题记录的完整面试报告（含“追问后修正”“证据不足”“声明矛盾”等真实情况）。

## 架构

```
src/
  lib/
    types.ts          # 复用 RAGFlow 的 CS Interview 类型 + 产品层类型
    theme.ts          # 深浅主题（data-theme 切换）
    storage.ts        # localStorage 草稿
    claims.ts         # 简历高风险声明（编辑后持久化，配置/面试页读取）
    mock/
      db.ts           # localStorage 数据层 + 演示数据 seed
      demo.ts         # 演示数据（简历 / JD / 题库 / 完整面试与报告）
      api.ts          # mock API（镜像后端协议，含面试状态机）
      report.ts       # 面试完成后的报告生成器
  hooks/
    use-cs-query.ts   # TanStack Query hooks + 查询键工厂
    use-interview-flow.ts # 实时面试流式状态（模拟 SSE 语义）
  components/
    layout/           # AppShell：顶栏 + 独立业务导航
    evidence/         # 证据轨道 / 溯源链（产品视觉记忆点）
    report/           # 雷达图 / 能力条
    upload/           # 文件拖拽上传
    ui/               # 按钮 / 输入 / 徽章 / 面板 / 弹窗 / Toast 等基础组件
  pages/
    Onboarding        # 首次引导：简历 → JD → 开始面试
    Overview          # 面试概览（匹配度 / 能力差距 / 最近面试）
    Resumes/Detail    # 简历中心（上传/解析/画像编辑）
    Jobs/Detail       # JD 中心（粘贴/上传/覆盖比对）
    Configure         # 新建面试（表单 + 计划摘要，草稿自动保存）
    Session           # 实时面试（双栏：答题 + 证据轨道上下文）
    Report            # 能力差距报告（JD 矩阵 / 逐题溯源 / 训练建议）
    Records           # 面试记录
```

## 设计

- 独立品牌：深色底 `#161618`、内容 `#1D1D20`、强调色 `#00BEB4`，
  区别于 RAGFlow 的蓝色系；细边框、低对比分区、紧凑密度、mono 数字排版。
- “证据轨道”：简历声明 → JD 要求 → 当前问题 → 回答证据 → 能力结论，
  面试页随回答动态推进，报告页作为可展开的溯源链路。
- 业务文案不出现 Planner / Judge / Dataset 等内部工程术语。
