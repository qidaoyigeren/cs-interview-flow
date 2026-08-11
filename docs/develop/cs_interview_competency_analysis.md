# CS Interview 升级前分析：执行链路 / 数据模型 / 风险

日期：2026-08-10。目标：为「CompetencySpec + Rubric 校准 + 证据级评分」升级提供基线。本文只做分析，不改变代码。

## 1. 当前执行链路

```
JD 粘贴/上传 ──> job_service.extract_job ──> 严格 JSON 校验(evidence span 必须在原文、
                                               topic 必须在 catalog、确定性权重)
Resume 上传 ──> resume_service.extract_resume ──> 抽取校验(claimed_skills/projects/stack)
Profile 创建 ──> match_resume_to_job(确定性匹配: explicit>inference>missing/unknown)
Session 创建 ──> InterviewSessionRepository.create ──> 一次性快照 profile/job/resume/
               match/initial_interview_plan/initial_candidate_state/知识配置/模型配置
                     └── build_initial_interview_plan
                         ROLE_CAPABILITY_TREES(topic→weight) + JD requirements + match risk
                         priority = jd_weight × risk_multiplier × category × focus
[start] ──> start_events ──> choose_planner_action_versioned(7 类动作, 确定性 rank_score)
  └─> generate_question: RAG 检索(三知识库 metadata filter) → validate_evidence
      → LLM 出题(grounding/leakage 校验) → code preflight → create_round → awaiting_answer
[answer] ──> answer_events
  ├─ judge_answer ──────────────────────────> 单次 LLM 调用 → score 0-4/verdict/covered/
  │                                            missing/factual_errors/needs_followup/
  │                                            followup_focus/weak_point/confidence
  │                                            (validate_judge_result + 低置信保守钳制 score<=2)
  ├─ extract_answer_state ──────────────────> claims/contradictions/covered_rubric_points/
  │                                            unverified_boundaries/deep_dive_branches
  ├─ merge_candidate_state ──> 追问才升级声明, 只解决被追问矛盾
  ├─ choose_after_answer_action ──> 矛盾>新声明>judge.needs_followup>planner
  │     ├─ followup → generate_followup → awaiting_followup (追问预算内)
  │     ├─ finish  → build_report → InterviewReport → completed
  │     └─ 下一题 → generate_question → preparing_question
```

关键事实：

- **评分规则完全内嵌在 prompt**。0-4 的语义锚点（0=空白/拒答/无关，1=有尝试但主要错误，2=部分要点，3=大部分要点，4=完整正确）只在 `JUDGE_SYSTEM_PROMPT` 文本里，没有任何结构化 `score_anchors` 或 per-competency rubric 版本。
- **Judge 是单阶段单次调用**，返回的 covered_points/missing_points 是无结构文本，不与回答片段（evidence span）绑定，无法实现「分数→证据」追溯。
- **Planner 是启发式 rank**：`rank_score = priority + contradiction_bonus + new_claim_bonus + untested_bonus − repeat_penalty − attempt_penalty`。无 `verification_uncertainty` / `expected_information_gain` / `comparability` 等显式因子，Replay 无法解释「为什么选这个动作」的因子分解。
- **计划以 JD requirement 为单位**，能力（competency）只是 topic 权重的扁平映射，没有 must-have 锚点覆盖、没有逐能力评分标准、没有「未覆盖≠低分」的显式状态机。
- **无锚点题组**。检索只按 `topic/difficulty/category` 过滤，同一能力在不同场次可能落到不同题（评分标准依赖知识库中的 rubric），可比性无法保证。
- 既有能力：确定性 Planner、领域规则、Operation/Event/Checkpoint/CAS/Lease、幂等、不可变快照、DTO 隐私白名单、Replay、实验版本绑定、trace/observability——这些必须全部保留。

## 2. 数据模型（现状）

| 表 | 用途 | 与本升级的关系 |
| --- | --- | --- |
| `interview_job` | JD + 结构化 requirements（权重确定性计算） | 保留；权重进入能力权重 |
| `interview_profile` | role/level/stack/topics/question_count/max_followups | 保留；新增 role policy 快照 |
| `interview_resume` | 简历 + 抽取 | 保留 |
| `interview_knowledge_config` | 三知识库 + 检索配置快照 | 保留；metadata 需支持 `anchor_group_id` |
| `interview_session` | 全部不可变快照 + planner/prompt 版本 + 状态/预算 | **新增** `competency_snapshot`/`rubric_snapshot`/`role_policy_snapshot`/`rubric_version` |
| `interview_round` | 题目/证据/答案/Planner 动作/Judge 结果 | **新增** `question_kind`/`competency_id`/`anchor_group_id`/`expected_evidence`/`rubric_version`/`evidence_evaluation`(三阶段产物) |
| `interview_report` | 确定性数值 + skill/JD 验证矩阵 | **新增** `competency_verification`（逐能力状态） |
| `code_submission` | 代码/可见/隐藏测试摘要 | 保留；代码题评分与测试结果冲突校验 |
| `interview_request` | 幂等 | 保留 |
| `interview_operation` / `interview_event` / `checkpoint` / `model_call` / `trace_event` | 持久化 worker/SSE/观测 | 保留 |
| `interview_evaluation_run/metric` | 评测运行持久化 | 扩展新指标 |
| `interview_feedback` / `review_action` | 反馈/治理 | 保留；标注任务可复用 |
| `interview_experiment*` / `pricing_version` | 实验/定价 | 保留 |

## 3. 与目标的差距（风险）分析

### 3.1 评分可比性不足（核心）
- 0-4 语义锚点无结构化定义，无法按能力/职级校准；同一 3 分在不同题、不同场次含义不同。
- 无 rubric 版本；知识库题目的 rubric 变更是运行时可变的，Session 运行中不冻结评分标准。

### 3.2 分数不可追溯到证据
- covered/missing points 是文本，无 `evidence_span_ids`；无法回答「这个分数来自回答里的哪句话」。
- 无一致性校验：高分但无证据、verdict 与 score 冲突、代码题得分与测试结果冲突、同一事实重复计分，均不会被拒绝。

### 3.3 覆盖性缺口
- must-have 是 JD 要求级别，不是能力级别；题量不足时可能跳过高权重能力，报告虽然标记 UNTESTED，但没有「未验证≠不掌握」的显式能力状态机，且面试过程中不阻止 skip。
- 锚点题缺位：能力覆盖依赖检索碰运气，同一能力的题组间评分标准可能不一致。

### 3.4 Planner 不可解释
- 无信息增益公式；因子不落盘，Replay 只能对比「选了啥」不能解释「为什么按这个优先级选」。
- 高权重低置信能力的追问、锚点未覆盖的 must-have 强制项缺失。

### 3.5 校准与人工标注不足
- `labeled_quality.json` 仅 12 条自洽合成样本（kappa=1.0 不能证明可信度）。
- 无多评审者独立标注、无 reviewer_evidence_spans / adjudicated_score、无 weighted kappa / macro F1 / 混淆矩阵 / anchor 稳定性 / 低置信准确率等指标。

### 3.6 500 条 RAG 挑战查询
- 已有 500 条生成查询（`review_status=model_generated_unreviewed`），无 `reviewer` 字段、无人工审核工具、`resume_eligible` 恒 false；需加审核工具并按比例门禁。

### 3.7 前端
- 会话页不展示「正在验证的能力」与提问原因（只有 selected_action + JD 要求 + resume probe）。
- 报告无证据轨道（JD→简历→锚点→追问→回答证据→能力结论）；无逐能力状态展示；「未覆盖」虽不显示为低分但缺少独立视觉状态。

### 3.8 测试与验收
- 现有测试覆盖状态机/幂等/Replay/泄漏；缺少：score_anchor 边界、evidence span 真实性、高分无证据拒绝、代码与评分冲突、must-have 锚点覆盖、题量不足未覆盖态、个性化追问不改变锚点能力、低置信复核、并发重试不重复副作用、报告与 Round 证据一致、标注不足输出 insufficient_sample。

## 4. 必须保留的既有契约（验收约束）

1. 状态机（session/round 转移）、CAS、Operation/Event/Checkpoint、Lease fencing、幂等重放、DTO 隐私白名单、SSE 去重。
2. 确定性 Planner 的「同输入同动作」；Replay 前向模拟；`decision_audit` 不进 LLM prompt。
3. 三知识库 metadata 规范、evidence validator、grounding/leakage 校验、code preflight。
4. 默认单元测试不访问真实 LLM/MySQL/Redis/ES/Runner；外部服务测试按 integration/e2e 隔离。
5. 不伪造人工标注、效果指标与生产数据；样本不足输出 `insufficient_sample`。
