# CS Interview 第三阶段交付报告

日期：2026-08-09。范围：生产质量闭环与运营平台建设（质量飞轮、可观测性、运营治理、灰度发布与成本优化）。

## 1. 修改文件清单

### 新增（后端）
- `api/apps/services/cs_interview/tracing.py` — 统一版本化 Trace 事件模型（`TraceEventKind` / `TraceEvent` / `TraceEmitter`），隐私白名单过滤，best-effort 批量落库
- `api/apps/services/cs_interview/replay.py` — 只读 Planner Replay（从不可变快照重建输入，逐 round 前向模拟，输出 deterministic / changed / unsupported_version）
- `api/apps/services/cs_interview/experiment_service.py` — 实验稳定分流（`stable_bucket`）、变体解析、assignment 冻结、guardrail 自动停止
- `api/apps/services/cs_interview/ops_service.py` — 质量总览聚合、会话审计、高频失败题、治理动作、反馈提交/列表、`_redact` 脱敏
- `api/apps/services/cs_interview/slo.py` — SLO 目标、告警规则与 runbook 链接、阶段延迟记录、租户预算
- `api/apps/services/cs_interview/eval_runs.py` — 评测运行持久化（`persist_run`）

### 修改（后端）
- `api/apps/services/cs_interview/domain.py` — 稳定 `contradiction_id`（`_contradiction_id`）、`merge_candidate_state` 只解决被追问矛盾（`resolved_contradiction_ids`）、`PlannerAction.target_contradiction_id`、`decision_audit` 决策审计、计划项 JD 权重分解字段、`ANSWER_STATE_VERSION` v2
- `api/apps/services/cs_interview/service.py` — 修复矛盾批解决（原 391-398），trace 事件接线（session_created / planner_action_selected / answer_received / judge_completed / answer_state_extracted / followup_selected / code_execution_completed / report_generated / session_completed / session_failed），阶段延迟记录
- `api/apps/services/cs_interview/pipeline.py` — `planner_action_prompt` 剔除 `decision_audit`（审计数据不进 LLM prompt），检索/出题 trace 事件（retrieval_started/completed、evidence_rejected、question_generated/rejected）
- `api/apps/services/cs_interview/evaluation.py` — `insufficient_sample`、95% Wilson 置信区间、`replay_determinism_ratio`、`labeled_stats`、`MIN_SAMPLES`/`SAFETY_METRICS`
- `api/apps/services/cs_interview/observability.py` — `TRACE_EVENT_WRITE_FAILURE`、`STAGE_LATENCY` 仪器
- `api/apps/services/cs_interview/quota.py` — 版本化价格（`get_pricing_config`，DB 活动行优先，env 内容哈希兜底）
- `api/apps/services/cs_interview/privacy.py` — `RetentionPolicy.trace_event_days` + 清理、导出公式注入防护 `_formula_safe`
- `api/apps/services/cs_interview/job_service.py` / `resume_service.py` — job_extracted / resume_extracted trace 事件
- `api/apps/services/cs_interview/worker.py` — 操作结束 `TRACE_EMITTER.flush()`、每小时 guardrail 自动停止检查
- `api/db/db_models.py` — 新增 10 张表（见 §2）
- `api/db/services/interview_service.py` — `create` 集成实验变体解析与 assignment 冻结
- `api/apps/restful_apis/cs_interview_api.py` — 运营/治理/反馈/实验端点（见 §2），`require_ops_admin` 二级鉴权

### 新增（测试/工具/配置）
- `test/unit_test/api/db/`：`test_cs_interview_trace.py`、`test_cs_interview_replay.py`、`test_cs_interview_experiments.py`、`test_cs_interview_eval_runs.py`、`test_cs_interview_ops_api.py`、`test_cs_interview_slo.py`；扩展 `test_cs_interview_agentic_domain.py`（矛盾/声明/审计）、`test_cs_interview_evaluation.py`（空样本/破坏/确定性）、`test_cs_interview_migration_smoke.py`（新表索引）
- `tools/cs_interview_scenarios_generate.py` — 确定性场景生成器（≥50 场景，`--check` 校验字节级一致）
- `tools/cs_interview_labeled_import.py` — 标注集校验 + Cohen's kappa + adjudication 统计
- `tools/cs_interview_eval.py` — 增加 `--labeled`、`--record-run`
- `test/fixtures/cs_interview/` — `agentic_scenarios.json`（8→50 场景）、`offline_eval.json`（retrieval/judge 扩至 6）、新增 `labeled_quality.json`
- `.github/workflows/cs-interview-beta.yml` — 新测试文件、`scenarios_generate.py --check`、`--labeled`

### 新增（前端）
- `web/src/pages/cs-interview/admin/`：`quality.tsx`、`sessions.tsx`、`session-detail.tsx`（含 Replay 对比）、`governance.tsx`、`feedback.tsx`
- `web/src/pages/cs-interview/__tests__/admin.test.tsx`
- 修改：`routes.tsx`（5 条 admin 路由）、`services/cs-interview-service.ts`（admin 端点）、`hooks/use-cs-interview-request.ts`（admin hooks + keys）、`interfaces/database/cs-interview.ts`（admin DTO）、`components.tsx`（admin 导航）、`locales/{en,zh}.ts`（admin i18n）

## 2. 新增表、API、页面

### 新表（10）
| 表 | 用途 | 关键索引 |
|---|---|---|
| `interview_trace_event` | 统一生命周期溯源 | (session_id, occurred_at)、(trace_id, occurred_at)、(tenant_id, occurred_at)、(event_type, occurred_at)、(round_id, occurred_at) |
| `interview_evaluation_run` | 评测运行（版本/git/指标） | create_time |
| `interview_evaluation_metric` | 每个阈值的指标行 | (run_id, metric) |
| `interview_experiment` | 实验定义（变体/流量/guardrail） | (status, start_at) |
| `interview_experiment_assignment` | 会话级变体冻结 | session_id 唯一、(experiment_id, session_id) 唯一 |
| `interview_feedback` | 候选反馈/申诉 | (tenant_id, create_time) |
| `interview_review_action` | 治理动作（坏题/下架/审核） | (resource_type, resource_id, create_time) |
| `interview_pricing_version` | 版本化价格 | active |

（保留策略：trace 默认 180 天，`CS_INTERVIEW_TRACE_EVENT_RETENTION_DAYS` 可调；清理在 `PrivacyService.cleanup`。）

### 新增 API（均 `@login_required`，admin 均 `is_superuser` + 分页）
- `GET /cs-interview/admin/quality/overview` — 质量总览（成功率/阶段失败率/P50·P95 延迟/token·成本/版本分布）
- `GET /cs-interview/admin/sessions` — 会话列表（状态过滤）
- `GET /cs-interview/admin/sessions/<id>/audit` — 时间线 + Planner 决策摘要 + 脱敏回答
- `POST /cs-interview/admin/sessions/<id>/replay` — 只读 Replay（确定性对比）
- `GET /cs-interview/admin/questions` — 高频失败题
- `POST /cs-interview/admin/review` — mark_bad / take_down / review
- `GET /cs-interview/admin/feedback` — 反馈列表（租户隔离）
- `POST /cs-interview/sessions/<id>/feedback` — 候选提交反馈（非 admin，关联版本）
- `GET|POST /cs-interview/admin/experiments`、`POST .../stop`、`GET .../assignments`

### 新增页面（主应用 `/cs-interview/admin/*`）
质量总览、会话审计列表、会话审计详情（时间线 + Replay）、题目与证据治理、用户反馈与申诉。导航在 `InterviewShell` 侧栏；服务端 403 为权威门禁，敏感字段需 `CS_INTERVIEW_OPS_SENSITIVE_ROLE`（env，默认空=仅 superuser）+ 审计。

## 3. 架构与事件流

```
候选人  →  REST/SSE  →  cs_interview_api.py
                           │
                    持久化 Operation (worker)
                           │
                ┌──────────┴──────────┐
                │  service.py          │
                │  ├─ choose_planner   │── decision_audit → planner_actions(round)
                │  ├─ generate_question│── retrieval/evidence/question trace
                │  ├─ judge/answer     │── judge/answer_state trace
                │  └─ report/finish    │── report/session_completed trace
                └──────────┬──────────┘
                    TRACE_EMITTER (统一事件，隐私白名单)
                           │ best-effort flush（独立事务，失败仅计数+告警）
                    interview_trace_event
                           │
              ops_service.py 聚合 → admin API → 前端运营页
              replay.py（只读，快照重建）→ /admin/sessions/<id>/replay
              experiment_service.py（会话创建时一次分流）→ assignment 冻结
```

统一关联：`trace_id` = `op-<operation_id>` / `req-<request_id>` / `sess-<session_id>`，Replay 用 `replay:<session_id>` 前缀。日志（`safe_log_context`）、指标（OTel）、Trace 共享同一 `trace_id/session_id/round_id`。

## 4. 质量指标定义与计算

全部来自真实执行：`evaluation.py` 对结构化输入调用真实 `choose_planner_action` / `choose_after_answer_action` 计算 `actual`，fixture 不存 `actual_action`。

| 指标 | 计算 | 门禁 |
|---|---|---|
| retrieval_recall_at_5 | expected_ids ∩ 前 5 retrieved / retrieval_cases | ≥0.85 |
| grounded_question_ratio | evidence_valid 题数 / questions | ≥0.95 |
| jd_requirement_question_coverage | covered requirements / total | ≥0.90 |
| must_have_coverage | covered must_have / total must_have | ≥0.85 |
| resume_claim_verification_rate | verified claims / total | ≥0.70 |
| answer_driven_branch_accuracy | actual==expected / branching | ≥0.85 |
| contradiction_followup_accuracy | resolve_contradiction / contradiction cases | ≥0.90 |
| jd_question_relevance | question topic ∈ requirement topic_ids | ≥0.95 |
| judge_human_agreement | judge score == human_score | ≥0.85 |
| hidden_answer_leakage_count | 序列化扫描私钥/片段 | ==0（安全） |
| ungrounded_generation_count | evidence_valid=false 题数 | ==0（安全） |
| report_numeric_consistency_ratio | build_report 与期望一致 | ==1.0（安全） |
| replay_determinism_ratio | Replay 动作 == 期望动作 | ==1.0（安全） |

- 每个指标输出样本数、分子/分母、95% Wilson 置信区间（`ci`）。
- 样本数低于 `MIN_SAMPLES` 时 `insufficient=true` 且 `passed=false`（绝不显示 100% PASS）。
- 任一安全指标非零或零样本 → 阻断发布。
- 每次评测持久化为 `interview_evaluation_run/metric`，含 git commit、模型、Prompt、Planner、知识库版本。

## 5. 隐私字段清单

以下内容**绝不进入** Trace 事件、审计、导出或日志：
- 完整 JD / 简历原文（`source_text`）
- 候选回答 / 源代码 / 参考答案 / 评分 rubric / 隐藏测试
- 检索证据原文 / prompt 快照 / 模型密钥（`_safe_model_snapshot` denylist）
- `answer` / `code_spec` / `content` / `statement` / `secret` / `password` / `api_key` 等键名（`_trace_safe_metadata`）

审计页/导出中敏感字段仅以 `_redact`（长度 + sha256 前缀哈希）呈现；CSV/JSON 导出经 `_formula_safe` 防公式注入。单测断言候选 DTO、运营 DTO、导出结构均无私有字段泄漏。

## 6. 测试命令与真实结果

```
.venv/Scripts/python.exe -m pytest test/unit_test/api/db/test_cs_interview_*.py -q
  → 118 passed（含新增 trace/replay/experiments/eval_runs/ops_api/slo）
.venv/Scripts/python.exe tools/cs_interview_scenarios_generate.py --check
  → agentic fixture is up to date (50 cases)
.venv/Scripts/python.exe tools/cs_interview_eval.py --labeled
  → CS interview offline gate: PASS（全指标含 CI）
.venv/Scripts/python.exe tools/cs_interview_labeled_import.py
  → labeled quality set: OK（12 条原创示例，kappa=1.0）
cd web && npx tsc --noEmit -p tsconfig.json  → cs-interview 范围 0 错误
cd web && npx oxlint <cs-interview 路径>    → 0 错误
cd web && npx jest --config jest.cs-interview.config.ts --runInBand src/pages/cs-interview
  → 13 passed（含新增 admin.test.tsx）
```

## 7. 未运行测试及原因

- 真实 MySQL / Redis / LLM / Runner 的 integration/e2e（`tools/cs_interview_live_*`、runner 冒烟）——本环境无外部服务与容器，未运行；命令见 `docs/develop/cs_interview.md` §11。
- 前端全量 jest / 全量 tsc —— 仓库既有其他模块的类型错误（user-setting、knowledge-service 等，非本次改动）；cs-interview 范围已通过。
- 浏览器 E2E（playwright）—— 需要完整部署栈，未运行。

## 8. 已知限制

- **Judge Replay 近似**：`needs_followup` 未直接持久化，重放由 round 列 + evaluation 重建，边缘场景（置信度触发的 followup 上限）可能与线上决策不完全一致；已记录为 Replay 的 `deterministic` 判定不包含此字段。
- **v1 旧数据兼容**：矛盾 `contradiction_id` 由 `_contradiction_id` 惰性补算，历史 round 可 merge；`ANSWER_STATE_VERSION` 已升至 v2。
- **trace 事件量**：每阶段 × 每轮 × 每会话为高频写入，内存缓冲 + 批量 flush + 180 天保留将其有界；生产负载测试应校验缓冲上限与保留天数。
- **二级鉴权**：敏感访问用 env 角色位而非完整 RBAC。
- **guardrail 自动停止**：`answer_request_failure_rate` 为占位（按操作失败追踪后续接线）；`session_failure_rate` 已生效并有测试。

## 9. 灰度发布与回滚

1. **离线门禁**：合并前跑 `tools/cs_interview_eval.py --labeled` 必须 PASS；生成器 `--check` 必须通过。
2. **可观测先行**：先部署 `interview_trace_event` 等新表（`init_database_tables` 幂等）+ worker（每小时 guardrail 检查），观察 trace 落库与 `TRACE_EVENT_WRITE_FAILURE`。
3. **实验灰度**：`POST /admin/experiments` 建实验，`traffic_percentage` 0→10→100 逐级；同一 session 变体冻结（assignment 行）。
4. **回滚**：实验 `stop` 紧急关闭（或 guardrail 自动停）；代码回滚为单体发布——服务端对新表缺失容忍（`resolve_variant`/`get_pricing_config` 均异常回退），旧前端不渲染 admin 路由。
5. **安全指标**：`hidden_answer_leakage_count`/`ungrounded_generation_count`/`report_numeric_consistency_ratio`/`replay_determinism_ratio` 任一非零即阻断发布。

## 10. 第一、二阶段遗留问题是否阻塞

**不阻塞。** 唯一的热路径改动（B1 矛盾修复）涉及 service.py 回答流与 domain.py merge，向后兼容（v1 旧行惰性补 id）；B2/A 为加性字段与 best-effort 事件，不影响既有会话。第一阶段的问答主链路与第二阶段持久化 worker 均未重写，无并行实现。
