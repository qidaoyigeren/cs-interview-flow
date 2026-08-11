# CS 模拟面试垂直应用

本文面向需要本地运行、测试或部署 CS 模拟面试应用的开发者。应用入口为 `/cs-interview`，REST/SSE 接口位于 `/api/v1/cs-interview`。

## 1. 架构与 owning runtime

业务 owning runtime 是现有 Python Quart API、Peewee 数据层和 RAGFlow 检索/模型运行时。持久化会话、状态迁移、幂等、出题策略、Judge、报告和代码提交均由服务端领域服务负责；不维护并行的 Canvas 或 Go 业务运行时。

一次面试的关键链路如下：

1. `job_service.py` 把粘贴或上传的 JD 当作不可信数据，要求模型返回严格 JSON，再由程序校验 evidence span、topic、长度、置信度和权重。非法 topic 会被移除，要求本身作为 unmapped requirement 保留。
2. Session 创建时确定性匹配 JD 与简历，并一次性保存 Profile、知识配置、JD、简历、匹配矩阵、初始计划、Competency/Rubric/锚点/角色策略快照（`interview_session.competency_snapshot`）。运行中不得回读可变化的 Job/Resume/Profile/能力配置代替快照。
3. Planner v2 按可审计的信息增益启发式选择受控动作：`action_value = jd_weight × verification_uncertainty × expected_information_gain × resume_risk − repetition_penalty − time_cost − comparability_penalty`；must-have 能力必须先锚定（`question_kind=anchor`），低分或低置信锚点不算完成；模型不能直接改变状态或突破边界。因子与决策审计落盘，Replay 逐项解释。
4. Query Builder 用 Planner 的 requirement/topic/action 构造查询。JD、简历和回答只决定“问什么”，不能作为技术事实来源。
5. 复用 RAGFlow `dataset_api_service.search` 的混合检索、metadata filter 和 rerank。普通题 Evidence Validator 接受元数据完整、`verified=true`、`quality_score>=0.6` 且 topic/难度一致的证据；锚点题还必须同时命中会话冻结的 `anchor_group_id` 与 `question_id`。
6. 锚点题直接读取审核过的固定题面与评分点，不经过 LLM 改写；缺少锚点证据时拒绝出题，不回退普通题。自适应题才由 Question Generator 结合 JD/简历生成，并经 grounding/leakage 校验。代码题必须用参考解答跑通 visible/hidden tests 后才能发送。
7. 每次回答进入证据级三阶段 Judge：Evidence Extractor（精确引文 span/claims/matched·missing indicators + Candidate State 子结构）→ Rubric Scorer（仅用不可变 Rubric 快照 0-4 锚点 + 提取证据 + 代码结果）→ Consistency Validator（分数↔锚点↔证据↔verdict↔代码一致性；失败受控重试一次，仍失败→低置信标记，绝不伪造确定结论）。新声明只有在 Planner 明确持久化 `target_claim_fact`、候选人回答对应追问且该追问得分达标后，才能逐条升级为已验证事实。
8. 报告数值、JD 验证矩阵与能力验证证据轨道均从持久化 round 确定性计算，LLM 不负责总分或验证状态。「未覆盖」能力独立显示且不计低分。

职级使用同一套 0～4 分语义保持横向可比，达标线分别为 junior=2、mid=3、senior=4、staff=4；会话快照同时冻结职级期望与默认难度，Planner、Candidate State 和报告均使用同一达标线。

检索和模型调用继续使用租户默认模型，因此 RAGFlow 已有的模型统计、日志和 Langfuse 上下文仍然生效。应用日志只记录 ID、状态、耗时、模型名、Judge 置信度和错误类型，不记录完整回答或源代码。

### 1.1 项目深挖（Project Deep-Dive）

项目经历是 Planner 的一级规划对象：约 70% 的题目围绕主项目深挖，其余 30% 由项目声明牵引出基础知识，同时保留固定锚点、RAG 证据契约、职级 Rubric、Judge 与可恢复执行链路。

- **简历抽取 v2（`EXTRACTION_VERSION = cs-interview-resume-extraction-v2`）**。每个项目输出结构化声明：`project_id`/`claim_id` 由系统对简历内容确定性哈希生成（模型不生成 ID）；`evidence_span` 必须是简历原文的连续文本（容忍标点/空白漂移但绝不接受编造）；`claim_type` 限定为 `architecture|technology_choice|mechanism|reliability|data_design|interface|metric|testing`；`risk_flags` 由程序对「提升性能/高可用/防止重复」等模糊表述、无理由选型、仅正常链路、关键词堆叠、无基线指标做确定性检测，并与模型建议取并集。旧版 v1 抽取必须重新抽取后才能创建画像/会话（`resume_outdated_extraction`）。
- **Project Attack Map（`build_project_attack_map`）**。会话创建时根据冻结的简历、JD 与 Competency 快照确定性生成，并随会话冻结（存于 `candidate_state.project_attack_map`，运行中只改状态不改结构）。优先选择与目标 JD 最相关的主项目；主项目覆盖 3～4 个有效维度，不机械遍历。冻结优先级综合 JD 权重 × 项目相关性 × 声明风险 × 验证不确定性 × 预期信息增益，再扣维度时间成本；风险驱动的维度增益会让「仅正常链路 → 优先故障边界」「可疑指标 → 优先指标验真」「无理由选型 → 优先替代方案」。相同输入必然得到相同 Attack Map。
- **Planner**。`PlannerAction` 新增 `target_project_id`/`target_claim_id`/`project_dimension`/`project_followup_depth`，动作尽量复用现有枚举，仅新增 `verify_project_claim`。必须能力未锚定时项目候选被整体排除，绝不挤掉固定锚点；锚点完成后，程序按已完成主问题计算项目/基础题占比，并选择使下一步最接近 `PROJECT_QUESTION_SHARE_TARGET=0.7` 的候选类型；只有一类候选时自动回退，计数与选择误差写入 `decision_audit.budget.question_mix`。同一 claim 的追问计数跨维度累计，达到 `PROJECT_CLAIM_MAX_FOLLOWUPS=2` 后切换维度/声明。回答中的 `project_facts` 保留 `project_id`/`claim_id` 归属，直接触发下一轮项目深挖，不再被合并为普通 `newly_claimed_fact`；归属校验会丢弃跨项目的事实，禁止跨项目串联。
- **RAG 出题**。项目声明只决定「验证什么」，技术事实、评分点与参考答案仍必须来自已验证的 RAG Evidence；`ResumeContext`/`ProjectContext` 始终视为不可信数据。自适应项目题明确引用简历声明（例如「你在 CS Interview Agent 中提到用 Operation/Event/Checkpoint 防止状态丢失，请解释一次 Worker 崩溃后的恢复过程」），固定锚点继续使用审核后的原题、不做项目个性化，无合格证据时拒绝出题，并防止泄露参考答案或一次捆绑多问。
- **Judge 与 Memory**。Judge 除技术评分外更新当前目标声明的验证状态（`untested/partial/verified/disputed/contradiction/low_confidence`）。`verified` 必须同时满足职级 `required_score`、足够置信度（≥0.7）与项目声明相关证据（提取器归因到该 claim 的 `project_fact`）；只更新当前 `target_claim_id`，同主题高分不能验证其他声明。回答中的 mechanism/decision/tradeoff/failure_mode/metric_definition 关联回 `project_id`/`claim_id`；新声明只能先成为待验证事实，不能在同一轮直接 verified；矛盾使用稳定 `contradiction_id`，只有明确追问过的矛盾可被解决。
- **Replay**。Planner 决策与项目声明状态均由不可变快照 + 已完成 round 确定性重放，`target_project_id`/`target_claim_id`/`project_dimension` 纳入决策身份比较（缺失字段归一化为空串，旧会话仍可重放）。
- **前端与报告**。面试页展示当前项目、正在验证的声明、深挖维度与追问进度（不泄露 Planner 权重与内部评分点）。报告新增「项目声明验真矩阵」：项目 → 简历声明 → 深挖维度 → 验证状态 → 回答证据 → 相关问题，并明确区分技术能力评分与项目声明可信度——「回答技术题得分高」不等同于「项目真实性已验证」。

## 2. 数据模型

启动时使用 RAGFlow 现有 `init_database_tables`/Peewee 建表与索引同步机制创建以下表，不存在单独的迁移系统：

| 表 | 用途 | 关键约束 |
| --- | --- | --- |
| `interview_job` | JD 来源、原文、结构化要求和抽取版本 | tenant/user 作用域；paste/file |
| `interview_profile` | Resume + Job 绑定、岗位、职级、题量、追问上限 | tenant/user 作用域；新建时两项都必须已抽取 |
| `interview_knowledge_config` | 三知识库绑定和检索/质量快照 | 三个 dataset ID 在保存时验证为不同 |
| `interview_session` | 状态、难度、Profile/JD/Resume/Match/Plan/CandidateState/Competency·Rubric·锚点快照 | `state_version` 乐观锁；业务运行只读快照 |
| `interview_round` | 私有题目、证据版本、答案状态、Planner 动作、question_kind/competency/锚点元数据、三阶段证据评估 | `(session_id, sequence)` 唯一；`(session_id, active_guard)` 唯一 |
| `interview_report` | 确定性数值、技能验证、JD 验证矩阵、能力验证证据轨道和项目声明验真矩阵 | `session_id` 唯一 |
| `interview_annotation_case` / `interview_annotation_review` / `interview_rubric_calibration` | Rubric 校准标注案例、多评审者打分、校准指标 | case_id 唯一；`(case_id, reviewer_id)` 唯一 |
| `code_submission` | 代码、执行状态、可见/隐藏测试摘要 | tenant/user/session 作用域 |
| `interview_request` | start/answer/code/abort 请求幂等结果 | `(session_id, request_id)` 唯一 |

`reference_answer`、`evaluation_rubric`、完整 `retrieval_evidence`、隐藏测试、Answer State、Planner supporting state/内部提示词和源代码不会通过候选人 DTO 序列化。候选人可见的是选中动作、目标 JD 要求、选择理由、简历 probe 摘要和证据 ID/来源元数据。

## 3. 状态机

Session 合法路径：

```text
created -> preparing_question -> awaiting_answer -> evaluating
                   ^                   |              |
                   |                   +--------------+ (追问)
                   +----------------------------------+ (下一题)
                                                      +-> completed
preparing_question/evaluating -> failed
非终态 -> aborted
```

Round 合法路径为 `preparing -> awaiting_answer -> evaluating -> awaiting_followup -> evaluating -> completed`。任一 session 同时只允许一个 `active_guard=active` 的 round。每个 session 状态更新带 compare-and-swap 版本条件并在事务中完成；相同 `request_id` 与相同 payload 重放持久化事件，不同 payload 返回 409。

允许动作固定为 `follow_up_current_claim`、`verify_resume_claim`、`verify_jd_requirement`、`verify_project_claim`、`resolve_contradiction`、`switch_topic`、`ask_coding_question`、`finish_interview`。题量、追问上限、难度边界、重复惩罚和状态迁移全部由程序控制。难度只有 `beginner / medium / advanced`：最终分 0–1 降一级，2–3 保持，4 分且上一题最终分至少 3 才升一级；边界不越界。回答产生的新声明只能先进入 CandidateState，后续独立验证后才能成为 verified fact。

## 4. 三知识库数据规范

必须创建三个不同且属于同一租户的知识库：面经、LeetCode 题解、八股文。每个文档都应完成解析，并包含：

```json
{
  "content_type": "interview_experience | leetcode | fundamentals",
  "role": "go_backend",
  "topic": "database.mysql",
  "difficulty": "medium",
  "question_id": "mysql-index-001",
  "anchor_group_id": "anchor-go_backend-database-mysql",
  "source": "原创内部培训材料",
  "source_date": "2026-01-01",
  "quality_score": 0.9,
  "verified": true,
  "license": "CC BY 4.0"
}
```

- 面经以单题或一个追问链为切片单位，额外记录公司、岗位、年份和轮次。
- LeetCode 类文档在同一文档/切片邻域内保留题干、约束、标准解法、复杂度、可见样例和隐藏测试。不要导入未获许可的大型题库。
- 八股文按一问一答组织，正文包含评分点、常见错误和可追问方向。
- must-have 能力的固定题额外包含 `anchor_group_id`；知识库绑定校验要求 14 个审核锚点组全部存在，避免运行时静默退化为普通题。
- `algorithm.core` 使用 `role=cs_general` 的跨岗位公共算法语料；其他 topic 仍按目标岗位精确过滤，避免为每个岗位复制同一道算法题。
- 文档内容始终作为不可信数据包在 `<untrusted_data>` 中；其中修改 system/Judge 规则的文字会被清理。

管理页面显示解析状态、文档/切片数、更新时间、元数据合格率和前 20 个问题。证据不足时流水线会重写查询、尝试同一目标 topic 的受控证据类别，最后返回 `insufficient_evidence`，不会用模型记忆补题。

## 5. 本地开发

先按仓库主文档启动数据库、Redis、对象存储和检索引擎，再下载依赖：

```bash
uv sync --python 3.13 --all-extras
uv run python3 ragflow_deps/download_deps.py
docker compose -f docker/docker-compose.yml -f docker/docker-compose.cs-interview-dev.yml --profile elasticsearch --profile cpu --profile cs-interview up -d --build
cd web && npm install && npm run dev
```

Runner 不映射宿主端口，并位于 `cs-interview-internal` 内部网络；只有同时加入该网络的 RAGFlow API 容器可以访问。如果要把 API 直接运行在宿主机，应使用 fake runner 做开发测试，或把 API 也放入该 compose 网络，不能把真实 runner 暴露到公网。若本机 Docker 或 unprivileged user namespace/bubblewrap 不可用，不得改为在 API 宿主机执行代码。

首次使用：

1. 在 RAGFlow 中配置租户默认 Chat、Embedding，并按需配置 Rerank 模型。
2. 创建并解析三个独立知识库，补齐上述 metadata。
3. 打开 `/cs-interview/knowledge` 保存并验证绑定。
4. 在 `/cs-interview/resumes` 上传、抽取并检查简历。
5. 在 `/cs-interview/jobs` 粘贴或上传 JD，执行抽取并人工修正结构化 JSON。
6. 打开 `/cs-interview/configure` 同时选择 Resume 与 Job，创建 Profile 并开始面试。

相关验证命令：

```bash
uv run pytest test/unit_test/api/db/test_cs_interview_domain.py
uv run pytest test/unit_test/api/db/test_cs_interview_agentic_domain.py
uv run pytest test/unit_test/api/db/test_cs_interview_evaluation.py
python tools/cs_interview_eval.py
# Rubric 校准标注集校验与指标（Windows 下经 pytest 验证，Linux CI 可直接运行）
python tools/cs_interview_calibration.py --check
# 500 条 RAG 挑战查询人工审核与 resume_eligible 门禁（review JSONL 输入）
python tools/cs_interview_rag_review.py review.jsonl --write
# 生成并校验 34 面经 + 33 算法 + 33 八股的公开实测语料
python tools/cs_interview_corpus_expand.py
python tools/cs_interview_kb_seed.py --validate-only
# 配置 RAGFLOW_API_KEY 后真实入库、召回评测与模拟面试
python tools/cs_interview_kb_seed.py --bind
python tools/cs_interview_live_retrieval_eval.py --include-manifest-smoke --summary-only
python tools/cs_interview_live_e2e.py --scenario go_runtime
python tools/cs_interview_live_e2e.py --scenario ai_backend_rag --force-extraction
cd web && npm run test -- --runInBand src/pages/cs-interview
cd web && npm run type-check && npm run lint && npm run build
```

## 6. 生产部署

Helm 沿用仓库现有 chart。先把 runner 镜像推送到内部镜像仓库，再设置：

```yaml
csInterviewRunner:
  enabled: true
  image:
    repository: registry.example.com/ragflow/cs-interview-runner
    tag: "2026.08.07"
  resources:
    requests: {cpu: 250m, memory: 256Mi}
    limits: {cpu: "1", memory: 384Mi}
```

Chart 会创建 ClusterIP Service、只允许 RAGFlow API/CS interview Worker Pod 入站且禁止 runner 出站的 NetworkPolicy，并把内部 URL 注入 API/Worker Pod。Service 使用 `ClientIP` affinity，使同一 Worker 的执行与进程组取消命中保存该 execution id 的同一 Runner Pod。Runner 使用非 root、只读根文件系统、内存卷、无 ServiceAccount token、`Localhost` 最小 seccomp profile、`allowPrivilegeEscalation=false` 和全部 capability drop。启用前必须把 `docker/cs-interview-runner/seccomp.json` 安装到每个节点的 kubelet seccomp root 下的 `profiles/ragflow-cs-interview.json`；不得用 `unconfined` 代替。

可调环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `CS_INTERVIEW_RUNNER_URL` | `http://cs-interview-runner:9390` | 内部 runner 地址 |
| `CS_INTERVIEW_RUNNER_TIMEOUT_SECONDS` | `8` | 后端调用总超时 |
| `CS_INTERVIEW_RUNNER_CPU_MS` | `3000` | 单次执行 CPU 上限 |
| `CS_INTERVIEW_RUNNER_MEMORY_MB` | `128` | 候选程序内存预算；Python 使用地址空间硬限制，Go/Node 使用运行时堆预算并由容器内存上限兜底 |
| `CS_INTERVIEW_RUNNER_PROCESSES` | `16` | 进程数上限 |
| `CS_INTERVIEW_RUNNER_OUTPUT_BYTES` | `8192` | stdout/stderr 上限 |
| `CS_INTERVIEW_MAX_ACTIVE_SESSIONS` | `2` | 单用户并发非终态 session |
| `CS_INTERVIEW_USER_WRITES_PER_MINUTE` | `30` | 单用户面试写操作速率 |
| `CS_INTERVIEW_EVAL_FIXTURE` | `test/fixtures/cs_interview/offline_eval.json` | 管理质量接口读取的离线评测 fixture |

这些变量不是密钥。模型/API 密钥继续通过 RAGFlow 现有密钥配置注入，不要写入 values 或 Git。`/api/v1/cs-interview/admin/quality`（管理员鉴权）同时返回知识质量和 runner 健康；runner 的 `/healthz` 只表示进程存活，`/readyz` 会通过真实 Bubblewrap namespace/rlimit 路径执行无害 self-test，只有后者成功时才接收代码任务。

数据库备份使用现有 MySQL/PostgreSQL 备份策略，并同时备份 RAGFlow 文档存储和检索索引。恢复时先恢复数据库与知识库，再启动 API/worker，最后验证三套知识库版本快照。日志平台应按 `session_id`/`round_id` 聚合；对回答和代码字段维持禁止采集规则。

## 7. 安全模型

- 所有 Job、Resume、Profile、Config、Session、CodeSubmission 查询同时约束 `tenant_id` 和 `user_id`；越界资源统一表现为 404。
- JD、简历、候选人回答、知识文档和代码都不能修改系统/Judge/Planner 规则。Prompt 对不可信数据加边界并过滤常见 instruction-injection 形式。
- 答案最多 20,000 字符，代码最多 50,000 字符，测试最多 50 个，编译输出最多保存 8,000 字符。
- Runner 不访问 Docker socket、宿主目录、内部凭据或公网。命令来自语言 allowlist 的固定 argv，绝不拼接 shell 字符串；超时杀死整个进程组。
- 候选人页面用不启用原始 HTML 的 Markdown 渲染路径。DTO 采用显式字段白名单，并有隐藏答案泄漏评测。
- 删除 Job/Resume 会移除源对象并使关联 Profile 不能再开新会话；正在引用 Resume 的 Session 会 abort，operation/event/checkpoint/prompt 副本会同步清理，仅保留匿名能力快照和原报告数值。`DELETE /sessions/{id}/personal-data` 用于显式终止并匿名化会话中的 JD、简历、回答、代码和 Planner 状态。
- 所有限流、并发 semaphore 和熔断状态使用现有共享 Redis；不存在进程内速率桶。Redis 不可用时配额检查 fail closed，DB operation 轮询仍可恢复已入队任务。

## 8. 受控生产 Beta 的故障窗口

持久化任务上线前确认并关闭的主要窗口如下：

| 故障点 | 原风险 | Beta 控制 |
| --- | --- | --- |
| API 接收后崩溃 | 幂等记录永久 processing | API 在同一事务创建 `InterviewOperation`/`InterviewRequest`，不执行长任务 |
| Worker claim 后崩溃 | Session 永久 preparing/evaluating | DB CAS claim、有限 lease、heartbeat；lease 过期后接管 |
| LLM 返回、业务提交前崩溃 | 重复调用和计费 | 确定性 call key + lease-fenced 外部结果 checkpoint |
| Round/Report/Code 提交后崩溃 | 重复副作用 | sequence/active guard、session report、operation code 唯一约束 |
| 业务提交、Event 前崩溃 | 客户端缺完成事件 | 恢复时读取已提交状态并补写 Event |
| Event 提交、客户端收到前断线 | 丢事件 | `(session_id, sequence)` 持久化日志和 `Last-Event-ID` 回放 |
| Event 与 checkpoint 之间崩溃 | 事件覆盖或重复 | Worker Event 和 event checkpoint 同事务；末事件精确重放去重 |
| abort 后 Worker 崩溃 | operation 永久 running | running 先置 cancellation requested；lease 到期 sweep 为 cancelled |
| 旧 Worker lease 丢失后返回 | 覆盖新结果或误 fail Session | checkpoint、Event、预算和终态写均校验 lease owner |

Operation 状态为 `pending/running/retry_wait/completed/failed/cancelled`；支持 `start_interview`、`prepare_question`、`evaluate_answer`、`generate_followup`、`prepare_next_question`、`generate_report`、`execute_code` 类型。当前复合 start/evaluate operation 通过 `current_stage` 和 checkpoint 恢复其 prepare/follow-up/report 子阶段。Redis Stream 仅用于低延迟唤醒，数据库 operation 是事实来源；Redis 短暂不可用时 Worker 继续轮询 DB。

429、provider 5xx、网络/检索/Runner 暂时错误和瞬时数据库/Redis 错误采用指数退避与抖动。无证据、schema 连续非法、状态冲突、Session 终止、安全/grounding 失败和预算耗尽为不可重试。默认最多 4 次 attempt、stage deadline 120 秒、operation deadline 300 秒，不允许无证据降级。本应用当前不启用模型 fallback；未来若启用，必须同时实现租户开关、原/备用模型、切换原因、实际 prompt snapshot、成本记录和相同 schema/grounding 校验。

## 9. SSE、幂等和隐私生命周期

- `GET /operations/{operation_id}` 是轮询事实来源；SSE 不可用不影响业务完成。
- `GET /sessions/{session_id}/events?operation_id=...&after_sequence=N` 支持 `Last-Event-ID`，先回放后等待，每 15 秒 heartbeat。客户端按 sequence 去重，断开不会取消 operation。
- 相同 request id + payload 返回原 operation/结果；不同 payload 返回 409。失败后业务重试必须使用新 request id。
- Event DTO 按 event type 白名单并递归移除 reference/rubric/evidence/hidden tests/prompt/checkpoint/source code。
- Session 列表、Event 回放和审计 API 均限制 page/limit，不允许无限历史加载。

数据分类：Resume/JD 原文、回答、代码和候选人项目事实为高敏感；reference/rubric/hidden tests/evidence/planner/checkpoint/prompt snapshot 为内部敏感；状态、耗时、模型、token、成本和匿名质量指标为运营数据。

| 环境变量 | 默认天数 | 数据 |
| --- | ---: | --- |
| `CS_INTERVIEW_RAW_DOCUMENT_RETENTION_DAYS` | 365 | 原始 Resume/JD |
| `CS_INTERVIEW_ANSWER_CODE_RETENTION_DAYS` | 365 | 回答、代码、prompt/checkpoint |
| `CS_INTERVIEW_SESSION_REPORT_RETENTION_DAYS` | 730 | Session/Report 个人内容 |
| `CS_INTERVIEW_IDEMPOTENCY_RETENTION_DAYS` | 7 | request idempotency |
| `CS_INTERVIEW_EVENT_RETENTION_DAYS` | 30 | SSE Event |
| `CS_INTERVIEW_AUDIT_RETENTION_DAYS` | 730 | 管理审计 |

`POST /privacy/deletions`、`GET /privacy/deletions/{id}`、`GET /privacy/export` 提供删除、状态和导出。删除被 Session 引用的 Resume 会 cancel operation、abort 活跃 Session、删除对象/索引/chunk，清理 event/checkpoint/prompt/result/request 副本，并仅保留匿名技能快照与报告数值。对象存储补偿失败会把删除请求标记为 failed 以便重试。

上传限制为 Resume 10 MiB、JD 5 MiB，同时执行用户文件数配额、MIME/扩展名/magic 一致性检查和可插拔恶意文件扫描。`CS_INTERVIEW_REQUIRE_MALWARE_SCANNER=true` 时扫描器不可用会 fail closed。

## 10. 分布式配额、指标和 SLO

Redis token bucket/lease semaphore 在所有副本间共享。核心配置：`CS_INTERVIEW_USER_WRITES_PER_MINUTE`、`CS_INTERVIEW_TENANT_LLM_RATE_PER_MINUTE`、`CS_INTERVIEW_MAX_ACTIVE_SESSIONS`、`CS_INTERVIEW_MAX_TENANT_RUNNING_OPERATIONS`、`CS_INTERVIEW_GLOBAL_JUDGE_CONCURRENCY`、`CS_INTERVIEW_GLOBAL_CODE_CONCURRENCY`、`CS_INTERVIEW_MAX_SESSION_TOKENS`、`CS_INTERVIEW_MAX_SESSION_COST`、`CS_INTERVIEW_MAX_RETRIEVALS_PER_OPERATION` 和 `CS_INTERVIEW_MAX_LLM_CALLS_PER_OPERATION`。未知模型价格标记 `cost_unknown`，不按 0 处理；管理员 usage API 只返回聚合，不返回原文。

OTel/现有导出器暴露 operation、LLM、retrieval、question、Judge、SSE、Session 和 Runner 指标。Prometheus label 仅允许 operation type、stage、status、error code、model、event type、language、result；tenant/user/session/round/request/operation ID 禁止作为 label。日志使用安全 tenant id、哈希 user id 和内部关联 ID，动态字段白名单禁止 prompt、回答、代码和 evidence 正文。

建议 Beta SLO/告警：Session 启动与 Answer 提交 5 分钟成功率 >= 99%；Question/Judge P95 <= 45/30 秒；SSE 重连回放成功率 >= 99.9%；stuck operation 15 分钟有增长即告警。无依据生成和隐藏答案泄漏错误预算恒为 0，offline eval 任一计数非 0 阻断发布。Runner readiness 失败、timeout 突增和可用副本低于 PDB 均告警。

## 11. 数据库升级、回滚与 CI

沿用 `init_database_tables -> migrate_db -> ensure_model_indexes`。升级顺序：先备份 MySQL/PostgreSQL、对象存储和检索索引；再部署 additive 表/列；nullable operation id 列与唯一索引分开创建；验证 migration smoke 后部署 Worker；再切新 API 和前端；最后启动归档清理。大表唯一索引应使用数据库支持的 online/concurrent DDL 运维步骤，不能假设 ORM 自动消除锁表风险。

混合版本窗口仅允许“新 schema/Worker + 尚未切流的旧 API”和短暂的新旧 API 副本共存。新 API 切流后不得回滚到 API 进程内长任务。应用回滚不能删除新表/列；数据库恢复必须使用升级前备份。

`.github/workflows/cs-interview-beta.yml` 在 Ubuntu 24.04/Python 3.13 使用冻结 `uv.lock`，门禁 Python unit/migration/DTO、offline eval、前端局部 lint/type-check/Jest coverage，以及 Runner Docker/Kind contract。普通 PR 不访问真实 LLM、Redis、MySQL、检索或对象存储。真实外部服务测试必须位于独立 integration workflow 且配置预算。

Runner 的 Go/Node 基础镜像锁定到多架构 digest；产物用 commit SHA 标记并记录 image SHA256。发布门禁使用固定版本漏洞扫描器检查 Critical、生成 SPDX JSON SBOM，并在 Docker 与 Kind 中安装同一 seccomp profile。故障注入覆盖 Python/Go/JavaScript timeout、内存、进程炸弹、输出洪泛、进程组取消、drain 和 Pod 删除恢复。

Windows 支持前端、编辑和纯 Python 领域单测，不是生产 Runner/CGO 验证平台。Python 3.13 Windows 上 `datrie`/`editdistance` 可能无可用 wheel；生产结论以冻结依赖的 Linux CI/container 为准，不得把 Windows fake 测试解释为 seccomp 通过。

```bash
uv sync --python 3.13 --group test --frozen
uv run pytest -q test/unit_test/api/db/test_cs_interview_*.py
uv run python tools/cs_interview_eval.py --json-output cs-interview-offline-eval.json
cd web && npm ci && npm run lint:cs-interview && npm run type-check:cs-interview
cd web && npm run test:cs-interview -- --watch=false
docker compose -f docker/docker-compose.yml config --quiet
helm lint helm --set csInterviewRunner.enabled=true --set csInterviewWorker.enabled=true
python tools/cs_interview_runner_smoke.py --base-url http://127.0.0.1:19390
python tools/cs_interview_runner_fault_injection.py --base-url http://127.0.0.1:19390 --drain
```

2026-08-09 的真实 Linux 容器故障注入使用 Docker Desktop Linux engine 29.2.1，在 `--cap-drop ALL --read-only --pids-limit 64 --memory 384m --cpus 1` 和仓库定制 seccomp profile 下执行。首次启动准确捕获 Go cache 的 metadata/xattr syscall 依赖，第二次 readiness 捕获 Bubblewrap 的 `signalfd` 与设备节点创建依赖；实现随后改为纯内容 cache copy、显式绑定四个最小 `/dev` 设备，并只放行实测需要的 `creat/signalfd/signalfd4`。最终 `/readyz` 返回 `sandbox_ok`，三语言正常执行、无网络 namespace、timeout、内存、进程炸弹、输出洪泛、进程组取消、drain 均通过，容器 restart 后再次通过 readiness 和三语言 smoke。对应命令就是上面的 `runner_smoke.py` 与 `runner_fault_injection.py --drain`，发布 CI 在 Docker 和 Kind 中重复执行同一契约。

## 12. 离线评测

`tools/cs_interview_eval.py` 使用 `test/fixtures/cs_interview/offline_eval.json` 的少量原创/合成样本，输出机器可读 JSON 和人类摘要。`test/fixtures/cs_interview/public_eval` 另带 100 篇原创改写的公开来源实测语料：34 篇面经、33 篇算法、33 篇八股；覆盖 Go、Java、Python、前端、机器学习、AI 应用后端、SDET 与通用基础。`tools/cs_interview_live_retrieval_eval.py` 可在真实 RAGFlow/Embedding 上运行人工改写、困难改写和一文一检三组指标。

离线指标包括 Recall@5、有证据比例、重复率、岗位相关性、难度匹配、Judge/人工标签一致率、JSON 有效率、追问合理率/违规数、无证据生成、报告数值一致性、隐藏答案泄漏，以及 `jd_requirement_question_coverage`、`must_have_coverage`、`resume_claim_verification_rate`、`answer_driven_branch_accuracy`、`contradiction_followup_accuracy`、`jd_question_relevance`、`grounded_question_ratio`、`judge_human_agreement`。`agentic_scenarios.json` 只保存结构化 plan/state/answer/judge 输入与 expected action；评测器实际调用当前 Planner 计算动作，fixture 不保存 `actual_action`。JD 要求覆盖率和简历声明验证率均进入发布门禁。该 fixture 明确包含 8 个场景、20 条要求和 14 条简历声明；它仍是合成回归集，不能解释为生产准确率。

新增 fixture 时必须保留来源/许可说明，不能复制大型商业题库。发布门禁使用需求中给定阈值；样本量会在输出中明确展示，不能把少量合成样本解读为生产准确率。

## 13. 已知限制

- 仓库的 100 篇公开实测语料用于回归与演示，不代表生产题库规模；上线仍需针对目标岗位扩充人工审核语料、困难负样本、时效性标注和版权治理。
- 模型调用、真实检索和容器沙箱集成测试需要外部服务。默认单元测试使用 fake runtime/fake runner，不访问 MySQL、MinIO、检索引擎、LLM 或 Docker。
- Runner 当前报告墙钟耗时；`memory_kb` 在无法获得可靠的单进程 cgroup 统计时为 0。Python 使用按请求设置的 `RLIMIT_AS`；Go 使用 `GOMEMLIMIT` 加 1 GiB `RLIMIT_AS`，Node 22 使用 `--max-old-space-size` 加实测可启动的 768 MiB `RLIMIT_AS`，外层 384 MiB Pod/container cgroup 仍是最终硬边界。单 Pod 串行执行候选程序，通过多副本/HPA 扩容，容量上线前仍需压测。
- Bubblewrap 需要 Linux 内核允许非特权 user namespace；不满足时 `/readyz` 失败且 Service 不接收任务，不能降级为宿主机执行。

## 14. 添加岗位或能力树

在 `api/apps/services/cs_interview/domain.py` 的 `ROLE_CAPABILITY_TREES` 增加一个稳定 role ID 和 topic 定义。当前包含 `ai_backend` 的 RAG、Agent 与大模型应用评测能力。每个 topic 必须声明名称、权重、适用难度、推荐题型、知识库类别、最低覆盖数、是否代码题和复测间隔。随后：

1. 为新 role/topic 添加带许可的知识库文档和规范 metadata。
2. 在前端岗位选项与中英文文案中加入 role。
3. 给 JD topic 映射、Planner 覆盖/风险排序、回答分支和避免连续同质题增加测试。
4. 扩展离线 fixture，验证岗位相关性、证据率、去重和难度匹配。
5. 不在 Prompt 中复制能力树；Prompt 只接收 Policy 的结构化决策。

## REST 与 SSE 接口速查

- `GET|POST /profiles`，`GET|PUT|DELETE /profiles/{id}`
- `GET|POST /jobs`，`POST /jobs/upload`，`GET|PATCH|DELETE /jobs/{id}`，`POST /jobs/{id}/extract`
- `GET|POST /resumes`，`GET|PATCH|DELETE /resumes/{id}`，`POST /resumes/{id}/extract`
- `GET /capabilities`
- `GET /knowledge/datasets`
- `GET|PUT /knowledge-config`，`POST /knowledge-config/validate`
- `GET|POST /sessions`，`GET /sessions/{id}`
- `POST /sessions/{id}/start`、`POST /sessions/{id}/answers`（创建持久化 operation，通常返回 202）
- `GET /operations/{operation_id}`，`GET /sessions/{id}/events?operation_id=...&after_sequence=...`
- `POST /sessions/{id}/code/run`，`POST /sessions/{id}/code/submit`
- `POST /sessions/{id}/abort`
- `GET /sessions/{id}/report`
- `DELETE /sessions/{id}/personal-data`
- `POST /privacy/deletions`，`GET /privacy/deletions/{id}`，`GET /privacy/export`
- `GET /admin/quality`，`GET /admin/usage`，`GET /admin/audit`

SSE 事件为 `answer_received`、`evaluating`、`feedback`、`followup_question`、`next_question`、`interview_completed` 和 `error`。
