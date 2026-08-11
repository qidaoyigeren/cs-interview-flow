# CS Interview Competency/Rubric 证据级升级报告

日期：2026-08-10。将「JD→Topic→Planner→RAG出题→Judge直接评分」升级为「岗位能力标准 → 统一锚点面试计划 → 确定性Planner → RAG/代码沙箱 → 回答证据抽取 → Rubric评分 → 一致性校验 → Candidate State → 追问/换题/低置信标记/结束」。本报告只陈述已实现并通过测试的事实，不填写不存在的人工一致率数据。

## 1. 架构变化

### 目标链路

```
岗位能力标准 (CompetencySpec/Rubric/锚点题组/RolePolicy)
   │  会话创建时冻结为不可变快照 (interview_session.competency_snapshot)
   ▼
统一锚点面试计划 (build_initial_interview_plan → 计划项带 competency_id/must_have)
   ▼
确定性 Planner v2 (action_value 信息增益公式，因子落盘)
   ▼
RAG/代码沙箱 (锚点题严格检索冻结 question_id/anchor_group_id；grounding/leakage/code preflight 不变)
   ▼
回答证据抽取 (Evidence Extractor：answer_spans/claims/matched/missing indicators)
   ▼
Rubric 评分 (Rubric Scorer：0-4 锚点 + 提取证据 + 代码结果)
   ▼
一致性校验 (Consistency Validator：分数↔锚点↔证据↔代码↔verdict；失败受控重试一次，仍失败→低置信)
   ▼
Candidate State → 追问/换题/结束 (choose_after_answer_action)
```

### 关键决策

- **单一路径，无新旧并行**。旧单次调用 Judge（`JUDGE_SYSTEM_PROMPT` + `_judge_payload`）及兼容包装函数整体移除，生产与测试统一调用三阶段 `evaluate_answer`。Planner 从 v1 就地演化为 v2（`SUPPORTED_PLANNER_VERSIONS = {v2}`），`choose_planner_action` 的排名改为信息增益启发式公式。
- **Competency 快照在会话创建时冻结**。`InterviewSessionRepository.create` 调用 `normalize_competency_snapshot(role, level)` 生成不可变快照存入 `interview_session.competency_snapshot`；运行中 Planner/Scorer 只读快照，绝不回读可变 catalog。
- **锚点题是硬契约**。14 个 must-have 能力均绑定审核过的固定 `question_id`、`anchor_group_id`、题面、难度和 Rubric；锚点轮次直接读取审核题面，不经过 LLM 改写。缺少题组证据时拒绝出题，不回退普通 topic 文档。知识库绑定校验会拒绝缺少任一锚点组的数据集。
- **职级标准不改变分数语义**。junior/mid/senior/staff 共用同一 0-4 量尺，分别以 2/3/4/4 为达标线，并冻结职级期望与默认难度；因此不同职级仍可比较，又不会把同一个“3 分”定义成不同含义。
- **不引入 LangGraph/LangChain/AutoGen/CrewAI；Canvas 不拥有 Session 状态**。持久化 Operation/Event/Checkpoint/CAS/Lease 架构不变。
- **未覆盖 ≠ 低分**。报告能力矩阵用 `uncovered`（score=None）独立表示；低置信结果进入 `insufficient_evidence`，绝不伪装成确定分数。

## 2. 数据模型变化

| 表 | 新增列 | 说明 |
| --- | --- | --- |
| `interview_session` | `competency_snapshot`(JSON)、`rubric_version`(char) | 能力/Rubric/锚点/RolePolicy 不可变快照 |
| `interview_round` | `question_kind`(anchor/adaptive/coding)、`competency_id`、`anchor_group_id`、`expected_evidence`(JSON)、`rubric_version`、`evidence_evaluation`(JSON) | 锚点元数据 + 三阶段 Judge 全量产物 |
| `interview_report` | `competency_verification`(JSON) | 逐能力证据轨道 + 结论状态 |
| `interview_annotation_case` | （新表） | 校准标注案例（question/answer/code/rubric快照/adjudicated_score） |
| `interview_annotation_review` | （新表） | 多评审者独立打分（reviewer_score/reviewer_evidence_spans/reviewer_reason） |
| `interview_rubric_calibration` | （新表） | 校准指标行（agent vs human 一致率等） |

迁移：`migrate_db` 新增 9 条 `alter_db_add_column`（additive），3 张新表由 `init_database_tables` 的 `DataBaseModel` 子类自动发现创建。

DTO：`public_round` 只向候选人暴露 `question_kind`/`competency_id`；`expected_evidence`/`evidence_evaluation`/`reference_answer`/`evaluation_rubric` 均不进入候选 DTO。管理员审计 `session_audit` 暴露脱敏后的证据审计（span 文本、低置信标记、action_factors）。

## 3. Planner v2 信息增益公式

```text
action_value =
    jd_weight                    × verification_uncertainty
    × expected_information_gain  × resume_risk
  - repetition_penalty - time_cost - comparability_penalty
```

| 因子 | 范围 | 语义与注释 |
| --- | --- | --- |
| `jd_weight` | [0,1] | JD 要求归一化权重（计划项 `jd_weight`，来自 JD 抽取）。 |
| `verification_uncertainty` | [0,1] | 该能力当前的不确定度：未尝试 0.85；disputed 0.8；partial/in_progress 0.65；已有≥2 条高置信证据降至 0.3。 |
| `expected_information_gain` | [0,1] | 再问一题预计改变多少判断：矛盾 0.95；新声明 0.9；无强证据 0.85；已有≥2 条高置信证据 0.4。 |
| `resume_risk` | [0,1] | 简历风险：missing/unknown=1.0、partial≈0.77、matched≈0.64（由 `risk_multiplier/2.2` 归一）。 |
| `repetition_penalty` | [0,1] | 近期同 topic 0.4 + 每次尝试 0.2，封顶 1.0。 |
| `time_cost` | [0,1] | beginner/medium/advanced 0.1/0.2/0.3，coding +0.15。 |
| `comparability_penalty` | [0,1] | 存在未锚定 must-have 能力时，非该能力的题目被惩罚 0.4～1.0（预算越紧越大）。 |

停止条件同时考虑：题量预算（`remaining_question_budget<=0`）、所有计划项终态、must-have 锚点覆盖完成 + 剩余最高 `action_value < PLANNER_FINISH_THRESHOLD(0.05)`（且无 protected 项）、未覆盖 must-have 不得跳过（protected guard 保留容量）。

`PlannerAction` 新增 `question_kind`/`competency_id`/`anchor_group_id`/`expected_evidence`/`action_factors`；`decision_audit` 保留候选排名与剔除原因。**相同输入始终产生相同动作**（纯函数；`action_factors` 供 Replay 逐项解释）。

## 4. Judge 三阶段流程

**阶段一 · Answer Evidence Extractor**（LLM，temperature 0）：提取 `answer_spans`（必须是原回答的连续精确引文，校验器丢弃不在回答中的 span）、`technical_claims/decisions/mechanisms/tradeoffs/examples`、`contradictions`、`uncertainty_phrases`、`matched_indicators`、`missing_indicators`，同时产出 Candidate State 所需的 answer_state 子结构（newly_claimed_facts 等）。

**阶段二 · Rubric Scorer**（LLM，temperature 0）：输入仅含 Rubric 快照（0-4 score_anchors + observable_indicators）、QuestionRubric、提取结果、代码 Runner 结果与必要题目上下文。输出 `score/matched_anchor/verdict/matched_indicators/missing_indicators/evidence_span_ids/confidence/needs_followup/followup_focus/weak_point/feedback/evaluation_summary/factual_errors`。

**阶段三 · Consistency Validator**（确定性，无 LLM）：校验分数==锚点、高分有证据、verdict↔score、confidence∈[0,1]、`evidence_span_ids` 真实存在、scorer 引用的 indicator 已被提取、同一 span 不重复计分、代码题得分不与测试结果冲突（全过却 0-1 分 / 编译失败却 4 分）、高分低置信。**失败受控重试评分器一次；仍失败 → 低置信结果**（confidence 封顶 0.3、needs_followup 置 false、`validator.passed=false`、`low_confidence=true`，feedback 加 `[低置信结果，需人工复核]`），**绝不静默接受错误 JSON，绝不强行生成确定性高分**。

低置信结果在报告能力矩阵中呈现为 `insufficient_evidence`（不判低分），并进入管理端复核。

## 5. 新增测试及执行结果

后端（`test/unit_test/api/db/`）：

| 文件 | 覆盖 | 结果 |
| --- | --- | --- |
| `test_cs_interview_competency_upgrade.py`（19 项） | 能力/Rubric 校验、真实题组与 manifest 对齐、职级达标线、低分锚点不算完成、Planner 确定性、Replay、报告证据一致 | ✅ |
| `test_cs_interview_calibration.py`（8 项） | 标注格式、评审者两两一致性、重复测量锚点稳定性、weighted kappa/macro F1/混淆矩阵、insufficient_sample | ✅ |
| `test_cs_interview_rag_review.py`（4 项） | 500 条 RAG 查询 reviewer 字段与 resume_eligible 门禁 | ✅ |
| 既有 17 个 cs_interview 测试文件 | 状态机/幂等/Lease/DTO 隐私/Replay/评估门禁等 | ✅ |

执行：`.venv/Scripts/python.exe -m pytest <全部 test_cs_interview_*.py> -q` → **164 passed**。

前端：`npx jest --config jest.cs-interview.config.ts --runInBand src/pages/cs-interview` → **17 passed**；`npm run type-check:cs-interview` → 0 diagnostics；`npx oxlint <cs-interview 范围>` → 0 错误。生产构建在 CI 上验证。

`tools/cs_interview_scenarios_generate.py --check` → 50 个 agentic 场景字节级一致；`tools/cs_interview_eval.py --labeled` → 离线门禁 PASS（指标含 95% Wilson CI）。

## 6. 人工校准数据模板

`test/fixtures/cs_interview/calibration_quality.json`（8 例，明确标注为合成/CI 用途，非生产准确率）：

```json
{
  "schema_version": "cs-interview-annotation-v1",
  "rubric_version": "cs-interview-rubric-v2",
  "model_version": "deepseek-v3",
  "prompt_version": "cs-interview-v1",
  "review_status": "synthetic_ci_only",
  "cases": [
    {
      "case_id": "cal-go-channel-001",
      "role": "go_backend", "competency_id": "go.runtime",
      "anchor_group_id": "anchor-go_backend-go-runtime",
      "question_id": "anchor-go-runtime-q1", "candidate_id": "candidate-001",
      "question": "…", "answer": "…", "code_result": null,
      "agent_score": 3, "agent_confidence": 0.82,
      "agent_low_confidence": false, "agent_followup": false,
      "reviews": [
        {"reviewer_id": "r1", "reviewer_score": 3, "reviewer_evidence_spans": ["…"], "reviewer_reason": "…"},
        {"reviewer_id": "r2", "reviewer_score": 3, "reviewer_evidence_spans": [], "reviewer_reason": "…"},
        {"reviewer_id": "r3", "reviewer_score": 2, "reviewer_evidence_spans": [], "reviewer_reason": "…"}
      ],
      "adjudicated_score": 3
    }
  ]
}
```

评测指标：Agent/人工完全一致率、误差≤1 分比例、加权 Cohen's Kappa、各能力 Macro F1、各分值混淆矩阵、低置信样本准确率、追问合理率、锚点能力覆盖率、锚点重复测量稳定性、Replay 确定率、报告数值一致率、隐藏答案泄漏数。评审一致性按评审者两两比较计算；锚点稳定性只比较同一候选人在同题组不同题上的分差，不混入候选人能力差异。生产指标最低样本门槛为 20～30；不足时统一标记 `insufficient_sample`。工具：`tools/cs_interview_calibration.py`。

500 条 RAG 挑战查询审核：`tools/cs_interview_rag_review.py` 读取 review JSONL（id/reviewer_id/status/note），逐条写入 `reviewer` 与 `review_status`；仅当人工审阅并 approved 比例 ≥0.8 且全覆盖后才把聚合 `resume_eligible` 置 true（当前 500 条仍为 `model_generated_unreviewed`，`resume_eligible=false`）。

## 7. 当前可证明的指标

- 164 个后端 cs_interview 单元测试通过，不访问真实 LLM/MySQL/Redis/ES/Runner。
- 前端 cs-interview 范围 17 个 Jest 测试通过、type-check 0、oxlint 0。
- Planner Replay 确定性在 50 个 agentic 场景上 == 1.0（`tools/cs_interview_scenarios_generate.py --check` 字节级一致）。
- 场景与校准 CLI 可在不启动 Quart/搜索/native 依赖的情况下独立运行；8 例数据明确标记 `synthetic_ci_only`，全部指标因样本不足显示 `INSUFFICIENT`。
- 500 条 RAG 查询具备 review_status 字段与 resume_eligible 门禁逻辑（未人工审阅，未标记 eligible）。

## 8. 尚不能写进简历的指标

- **Agent/人工一致率**：当前标注集为 8 例合成样本，不构成可信一致率；需要真实多人标注与 adjudication 后才有数值。
- **真实检索 Recall / 端到端面试通过率**：需真实 LLM/MySQL/ES/Runner 的 integration/e2e（本环境无外部服务，未运行）。
- **生产 Latency/P95**：证据级 Judge 每回答 2 次 LLM 调用（抽取+评分），真实延迟未测量。
- **线上覆盖与效果**：真实题库规模、困难负样本、时效性标注均未扩充。

## 9. 改造前后完整流程图

改造前：
```
JD → Topic → Planner(启发式 rank) → RAG 出题 → Judge 直接评分(单次 LLM, 文本锚点)
                                          └→ 0-4 分/covered/missing 文本，无证据绑定
```

改造后：
```
岗位能力标准(冻结快照)
  → 统一锚点面试计划(competency/must_have)
  → Planner v2(action_value 信息增益, 因子落盘, must-have 锚点守卫)
  → RAG 出题(锚点题严格命中冻结题组，缺失即拒绝) / 代码沙箱(preflight 不变)
  → Evidence Extractor(精确引文 span) → Rubric Scorer(0-4 锚点)
  → Consistency Validator(通过/重试一次/低置信标记)
  → Candidate State → 追问(自适应, 不改变锚点能力)/换题/结束
  → 报告能力证据轨道(JD→简历→锚点→追问→回答证据→结论, 未覆盖≠低分)
```

## 10. 可以基于真实实现更新的简历表述

- 「为 CS 模拟面试实现**结构化能力标准与可校准 Rubric**：每个岗位的能力 0-4 分锚点都映射到可观察行为，Rubric 版本化并在会话创建时冻结为不可变快照。」
- 「将单次 LLM Judge 重构为**证据级三阶段评分**（证据抽取 → Rubric 评分 → 一致性校验），每个分数可追溯到回答中的具体证据片段；不一致结果受控重试并降级为低置信，绝不伪造确定结论。」
- 「实现**信息增益驱动的确定性 Planner**：action_value 显式分解为 JD 权重×验证不确定性×预期信息增益×简历风险−重复惩罚−时间成本−可比性惩罚，因子与决策审计落盘，支持 Replay 逐项解释，确定性 100%。」
- 「建立**固定锚点题 + 自适应追问**的可比性机制：14 个 must-have 能力绑定审核题面与版本化 Rubric，缺少锚点证据时拒绝出题；个性化追问仅发生在后续层，未覆盖能力不计低分。」
- 「构建**Rubric 校准与人工标注工具链**：多评审者独立标注格式、加权 Cohen's Kappa/Macro F1/混淆矩阵/锚点稳定性等指标、样本不足输出 insufficient_sample，以及 500 条 RAG 挑战查询的人工审核与 resume_eligible 门禁。」

注意：以上均为**实现能力**表述；Agent 与人工一致率等**效果数值**须在真实标注数据齐备前保持空白。

## 11. 尚未完成的生产改进（诚实清单）

- 真实多人标注集与 adjudication（当前仅 8 例合成）。
- 证据级 Judge 在真实模型上的校准（latency/一致率/低置信率）。
- 每个能力当前只有一个固定锚点题；若要测量“等价题组稳定性”，仍需补充同构题并对同一批候选人做重复测量。
- `interview_rubric_calibration`/`interview_annotation_*` 表的持久化标注工作流与前端增删改（当前只读展示）。
- 500 条 RAG 查询的人工审阅实际执行（门禁逻辑已就绪）。
