<div align="center">
<h1>CS Interview Flow</h1>
<p><b>基于 RAGFlow 检索/Agent 引擎构建的 CS 模拟面试平台</b></p>
</div>

<p align="center">
    <a href="./LICENSE">
        <img height="21" src="https://img.shields.io/badge/License-Apache--2.0-ffffff?labelColor=d4eaf7&color=2e6cc4" alt="license">
    </a>
</p>

> [!NOTE]
> 本项目基于 [infiniflow/ragflow](https://github.com/infiniflow/ragflow)（Apache-2.0）二次开发，复用其检索引擎、Agent 运行时和文档解析能力，在此之上构建了独立的 CS 模拟面试垂直应用。完整的架构、部署与 API 文档见 [docs/develop/cs_interview.md](./docs/develop/cs_interview.md)。

<details open>
<summary><b>📕 目录</b></summary>

- 💡 [这是什么](#-这是什么)
- 🌟 [核心能力](#-核心能力)
- 🔎 [架构概览](#-架构概览)
- 🚀 [本地开发](#-本地开发)
- 🎬 [生产部署](#-生产部署)
- 🔒 [安全与隐私](#-安全与隐私)
- 📚 [文档](#-文档)
- 🙌 [致谢](#-致谢)

</details>

## 💡 这是什么

CS Interview Flow 是一套面向计算机岗位（后端、AI 应用、算法等）的**模拟面试**应用：候选人上传简历、粘贴目标 JD，系统据此规划提问、检索证据支撑的题目、评估回答、追问、给出报告,并支持真实代码题的沙箱执行。

面试的出题、追问、评分和状态迁移全部由程序化的 Planner / Judge / 状态机控制，模型只负责在给定证据和结构化决策下生成自然语言,不允许自行改变流程或凭空编题。检索、模型调用与文档解析复用 RAGFlow 已有的能力。

## 🌟 核心能力

- **JD 与简历结构化抽取**：将粘贴/上传的 JD、简历当作不可信数据，抽取要求、声明并校验 evidence span、topic、置信度。
- **三知识库检索出题**：面经、LeetCode 题解、八股文三个独立知识库，出题前做 grounding 校验，无证据直接拒绝出题，不用模型记忆编题。
- **确定性 Planner**：基于 JD 权重、简历风险、覆盖率、追问预算和难度边界选择下一步动作（追问 / 验证声明 / 切换话题 / 代码题 / 结束）。
- **双轨评估**：每次回答同时进入 Judge 打分与 Answer State 抽取，新声明需要独立追问验证后才能升级为已验证事实。
- **沙箱代码执行**：非 root、只读根文件系统、seccomp、cgroup 限额的隔离 Runner，支持 Python/Go/Node 代码题的可见/隐藏测试。
- **幂等与故障恢复**：Operation/Event/Checkpoint 全链路带 CAS 版本、lease 和幂等键，覆盖 API 崩溃、Worker 崩溃、断线重连等故障窗口。
- **配额、可观测性与隐私生命周期**：跨副本共享的 Redis 限流、OTel 指标、分级数据留存与删除/匿名化接口。

## 🔎 架构概览

业务 owning runtime 是 RAGFlow 现有的 Python Quart API、Peewee 数据层与检索/模型运行时；不维护并行的 Canvas 或 Go 业务运行时。核心链路、状态机、数据模型、REST/SSE 接口详见 [docs/develop/cs_interview.md](./docs/develop/cs_interview.md)。

RAGFlow 引擎本身（文档解析、混合检索、Agent 工作流等）的架构说明见上游文档：[ragflow.io/docs](https://ragflow.io/docs/dev/)。

## 🚀 本地开发

前置条件与通用 RAGFlow 环境一致：

- CPU >= 4 核，RAM >= 16 GB，Disk >= 50 GB
- Docker >= 24.0.0 & Docker Compose >= v2.26.1
- Python >= 3.13

```bash
uv sync --python 3.13 --all-extras
uv run python3 ragflow_deps/download_deps.py
docker compose -f docker/docker-compose.yml -f docker/docker-compose.cs-interview-dev.yml \
  --profile elasticsearch --profile cpu --profile cs-interview up -d --build
cd web && npm install && npm run dev
```

首次使用需要：配置租户默认 Chat/Embedding 模型 → 创建并解析三个知识库（面经/算法/八股）→ 在 `/cs-interview/knowledge` 绑定 → 上传简历、粘贴 JD → 创建 Profile 并开始面试。完整步骤、验证命令和 fixture 见 [docs/develop/cs_interview.md §5](./docs/develop/cs_interview.md#5-本地开发)。

## 🎬 生产部署

沿用仓库现有 Helm chart，额外开启 `csInterviewRunner` 和 `csInterviewWorker`：

```yaml
csInterviewRunner:
  enabled: true
  image:
    repository: registry.example.com/ragflow/cs-interview-runner
    tag: "2026.08.07"
```

Runner 以 ClusterIP 运行在内部网络中，禁止出站、非 root、只读根文件系统，并要求宿主机安装仓库自带的 seccomp profile。详见 [docs/develop/cs_interview.md §6](./docs/develop/cs_interview.md#6-生产部署)。

## 🔒 安全与隐私

- 所有面试相关资源查询均同时校验 `tenant_id` 与 `user_id`，越权统一返回 404。
- JD、简历、回答、知识文档、代码均视为不可信数据，不能修改系统/Judge/Planner 规则。
- 代码沙箱不访问 Docker socket、宿主目录或公网，命令走固定 argv 白名单。
- 提供 `DELETE /sessions/{id}/personal-data` 与 `/privacy/deletions`、`/privacy/export` 接口用于数据删除、状态查询与导出。

完整安全模型见 [docs/develop/cs_interview.md §7](./docs/develop/cs_interview.md#7-安全模型)。

## 📚 文档

- [docs/develop/cs_interview.md](./docs/develop/cs_interview.md) — CS 模拟面试应用的完整架构、数据模型、REST/SSE 接口、部署与运维文档
- [docs/develop/cs_interview_phase3.md](./docs/develop/cs_interview_phase3.md)、[docs/develop/cs_interview_eval_report_2026-08-08.md](./docs/develop/cs_interview_eval_report_2026-08-08.md) — 迭代与评测记录
- RAGFlow 引擎本身的用户/开发者文档：[ragflow.io/docs](https://ragflow.io/docs/dev/)

## 🙌 致谢

本项目基于 [InfiniFlow](https://github.com/infiniflow) 团队开源的 [RAGFlow](https://github.com/infiniflow/ragflow) 构建，感谢其在文档理解、混合检索与 Agent 运行时上的工作。项目遵循 [Apache License 2.0](./LICENSE)。
