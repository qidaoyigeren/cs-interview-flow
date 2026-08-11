/**
 * 演示数据：Go 后端校招生 × 中级 Go 后端开发岗位。
 * 包含真实的不完美结果：回答不足、追问后修正、简历声明未被证明等。
 */
import type {
  CodeSubmission,
  InterviewCategory,
  InterviewDatasetOption,
  InterviewDifficulty,
  InterviewJob,
  InterviewKnowledgeConfig,
  InterviewProfile,
  InterviewReport,
  InterviewResume,
  InterviewRound,
  InterviewSession,
  JDRequirement,
  ResumeExtraction,
} from '@/lib/types';
import type { HighRiskClaim } from '@/lib/types';

/* ---------------- 基础 ID ---------------- */
export const IDS = {
  resume: 'res_demo_go_01',
  job: 'job_demo_go_mid',
  profile: 'prof_demo_go_01',
  sessionCompleted: 'ses_demo_completed_01',
  sessionActive: 'ses_demo_active_01',
  submission: 'sub_demo_01',
};

/* ---------------- 简历 ---------------- */
export const demoResumeExtraction: ResumeExtraction = {
  targetRole: 'Go 后端开发工程师',
  targetLevel: '校招 · 初级',
  technologyStack: ['Go', 'MySQL', 'Redis', 'Kafka'],
  yearsOfExperience: 1,
  summary:
    '计算机专业本科应届，近一年 Go 后端实习与项目经验。熟悉 Go 并发编程、MySQL 索引优化、Redis 缓存与 Kafka 消息队列；在“基于 RAG 的智能面试系统”中承担后端核心开发，负责问答召回服务与高并发链路。',
  claimedSkills: [
    {
      skill: 'Go 并发编程',
      claimedLevel: 'proficient',
      topics: ['goroutine', 'channel', 'GMP 调度', '内存模型'],
    },
    {
      skill: 'MySQL 数据库',
      claimedLevel: 'experienced',
      topics: ['索引', '事务隔离', '慢查询优化'],
    },
    {
      skill: 'Redis 缓存',
      claimedLevel: 'experienced',
      topics: ['缓存穿透/击穿/雪崩', '分布式锁'],
    },
    {
      skill: 'Kafka 消息队列',
      claimedLevel: 'familiar',
      topics: ['生产者/消费者', '消费堆积'],
    },
    {
      skill: 'RAG 系统开发',
      claimedLevel: 'experienced',
      topics: ['召回', '向量检索', 'Prompt'],
    },
  ],
  projects: [
    {
      name: '基于 RAG 的智能面试系统',
      role: '后端负责人',
      summary:
        '从 0 搭建问答召回与面试流程服务：负责向量召回接口、缓存分层与消息削峰，支撑高并发提问与实时评估。',
      skills: ['Go', 'MySQL', 'Redis', 'Kafka', 'RAG'],
    },
  ],
  extractionVersion: '1.0',
};

export const demoResume: InterviewResume = {
  id: IDS.resume,
  fileName: '张三-Go后端-简历.pdf',
  fileType: 'pdf',
  parseStatus: 'parsed',
  chunkCount: 46,
  extraction: demoResumeExtraction,
  extractedAt: '2026-08-08T09:30:00.000Z',
  createdAt: '2026-08-08T09:28:00.000Z',
  updatedAt: '2026-08-08T09:30:00.000Z',
  preview: {
    name: '张三',
    skills: ['Go', 'MySQL', 'Redis', 'Kafka'],
    projectNames: ['基于 RAG 的智能面试系统'],
  },
};

export const demoHighRiskClaims: HighRiskClaim[] = [
  {
    id: 'hrc_01',
    claim: '熟练使用 Redis 分布式锁解决缓存一致性',
    source: '项目经历·基于 RAG 的智能面试系统',
    reason: '声称“熟练”，但项目描述中缺少对锁超时、可重入与主从切换边界的细节，容易被追问暴露。',
    topics: ['缓存'],
  },
  {
    id: 'hrc_02',
    claim: '主导 Kafka 消费者稳定性治理',
    source: '项目经历·基于 RAG 的智能面试系统',
    reason: '校招经历中“主导”程度存疑，需要追问实际落地措施（重平衡、位移提交、堆积告警）。',
    topics: ['Kafka'],
  },
  {
    id: 'hrc_03',
    claim: '深入理解 Go 内存模型',
    source: '技能自述',
    reason: '技能自述与实际项目使用深度不符，内存序与同步原语是高频追问点。',
    topics: ['Go 并发'],
  },
];

/* ---------------- JD ---------------- */
export const demoJobRequirements: JDRequirement[] = [
  {
    requirementId: 'req_01',
    text: '熟练掌握 Go 语言核心，理解并发模型（GMP）、内存模型与 GC 机制',
    category: 'must_have',
    skills: ['Go'],
    topicIds: ['go-concurrency'],
    expectedLevel: 'advanced',
    weight: 0.9,
    evidenceSpan: '任职要求',
    extractionConfidence: 0.95,
    unmapped: false,
  },
  {
    requirementId: 'req_02',
    text: '熟悉 MySQL 索引原理与事务隔离级别，能定位并优化慢查询',
    category: 'must_have',
    skills: ['MySQL'],
    topicIds: ['mysql'],
    expectedLevel: 'medium',
    weight: 0.8,
    evidenceSpan: '任职要求',
    extractionConfidence: 0.93,
    unmapped: false,
  },
  {
    requirementId: 'req_03',
    text: '熟悉 Redis 常见缓存问题（穿透/击穿/雪崩）并给出工程化方案',
    category: 'must_have',
    skills: ['Redis'],
    topicIds: ['redis'],
    expectedLevel: 'medium',
    weight: 0.8,
    evidenceSpan: '任职要求',
    extractionConfidence: 0.9,
    unmapped: false,
  },
  {
    requirementId: 'req_04',
    text: '理解 Kafka 消息语义，能处理消费堆积与重平衡下的稳定性问题',
    category: 'must_have',
    skills: ['Kafka'],
    topicIds: ['kafka'],
    expectedLevel: 'medium',
    weight: 0.7,
    evidenceSpan: '任职要求',
    extractionConfidence: 0.88,
    unmapped: false,
  },
  {
    requirementId: 'req_05',
    text: '具备分布式系统设计与高并发架构思路，能应对压测与容量规划',
    category: 'must_have',
    skills: ['系统设计'],
    topicIds: ['system-design'],
    expectedLevel: 'medium',
    weight: 0.9,
    evidenceSpan: '任职要求',
    extractionConfidence: 0.85,
    unmapped: false,
  },
  {
    requirementId: 'req_06',
    text: '熟悉 HTTP/TCP 基础，能描述常见网络异常与幂等方案',
    category: 'must_have',
    skills: ['网络'],
    topicIds: ['network'],
    expectedLevel: 'beginner',
    weight: 0.5,
    evidenceSpan: '任职要求',
    extractionConfidence: 0.82,
    unmapped: false,
  },
  {
    requirementId: 'req_07',
    text: '了解 Docker 与 Kubernetes 基本部署与资源管理',
    category: 'nice_to_have',
    skills: ['Docker', 'K8s'],
    topicIds: ['container'],
    expectedLevel: 'beginner',
    weight: 0.3,
    evidenceSpan: '加分项',
    extractionConfidence: 0.8,
    unmapped: false,
  },
];

export const demoJobSourceText = `岗位：中级 Go 后端开发工程师
工作职责：
- 负责核心业务服务的架构设计与开发，保障高并发下的稳定性；
- 参与消息队列、缓存、数据库等基础设施的选型与治理；
- 参与线上压测、容量规划与故障排查。

任职要求：
1. 熟练掌握 Go 语言核心，理解并发模型、内存模型与 GC 机制；
2. 熟悉 MySQL 索引原理与事务隔离级别，能定位并优化慢查询；
3. 熟悉 Redis 常见缓存问题（穿透/击穿/雪崩）并给出工程化方案；
4. 理解 Kafka 消息语义，能处理消费堆积与重平衡下的稳定性问题；
5. 具备分布式系统设计与高并发架构思路，能应对压测与容量规划；
6. 熟悉 HTTP/TCP 基础，能描述常见网络异常与幂等方案。

加分项：
- 了解 Docker 与 Kubernetes 基本部署与资源管理；
- 有监控体系（Prometheus/Grafana）建设经验。`;

export const demoJob: InterviewJob = {
  id: IDS.job,
  name: '中级 Go 后端开发工程师',
  sourceType: 'paste',
  sourceText: demoJobSourceText,
  extraction: {
    requirements: demoJobRequirements,
    unmappedRequirementIds: [],
    extractionVersion: '1.0',
  },
  extractionVersion: '1.0',
  extractedAt: '2026-08-08T10:02:00.000Z',
  createdAt: '2026-08-08T10:00:00.000Z',
  updatedAt: '2026-08-08T10:02:00.000Z',
};

/* ---------------- 画像 ---------------- */
export const demoProfile: InterviewProfile = {
  id: IDS.profile,
  name: '张三',
  targetRole: 'Go 后端开发工程师',
  targetLevel: '中级',
  technologyStack: ['Go', 'MySQL', 'Redis', 'Kafka'],
  focusTopics: ['go-concurrency', 'mysql', 'redis', 'kafka', 'system-design', 'algorithms'],
  excludedTopics: ['frontend'],
  initialDifficulty: 'medium',
  preferredCategories: ['baguwen', 'interview_experience', 'leetcode'],
  questionCount: 6,
  maxFollowups: 2,
  resumeId: IDS.resume,
  jobId: IDS.job,
  createdAt: '2026-08-08T10:05:00.000Z',
  updatedAt: '2026-08-08T10:05:00.000Z',
};

/* ---------------- 知识源 ---------------- */
export const demoDatasets: InterviewDatasetOption[] = [
  {
    id: 'ds_interview',
    name: '面试经验库',
    documentCount: 128,
    chunkCount: 3240,
    embeddingModel: 'BGE-M3',
    updatedAt: '2026-08-07T08:00:00.000Z',
  },
  {
    id: 'ds_leetcode',
    name: '算法题库',
    documentCount: 210,
    chunkCount: 980,
    embeddingModel: 'BGE-M3',
    updatedAt: '2026-08-07T08:00:00.000Z',
  },
  {
    id: 'ds_fundamentals',
    name: '基础八股库',
    documentCount: 86,
    chunkCount: 2410,
    embeddingModel: 'BGE-M3',
    updatedAt: '2026-08-07T08:00:00.000Z',
  },
];

export const demoKnowledgeConfig: InterviewKnowledgeConfig = {
  id: 'kc_01',
  interviewExperienceDatasetId: 'ds_interview',
  leetcodeDatasetId: 'ds_leetcode',
  fundamentalsDatasetId: 'ds_fundamentals',
  retrievalConfigSnapshot: {
    similarityThreshold: 0.5,
    vectorSimilarityWeight: 0.6,
    topN: 5,
    topK: 3,
    rerankId: '',
  },
  metadataQualitySnapshot: {},
  enabled: true,
  createdAt: '2026-08-08T10:06:00.000Z',
  updatedAt: '2026-08-08T10:06:00.000Z',
};

/* ---------------- 题库 ---------------- */
export interface BankCodingSpec {
  language: 'go' | 'python' | 'javascript';
  starterCode: string;
  visibleTests: Array<{ name: string; input: string; expected: string }>;
  hiddenTotal: number;
  hint: string;
}

export interface BankQuestion {
  id: string;
  category: InterviewCategory;
  topic: string;
  questionType: 'theory' | 'scenario' | 'coding';
  difficulty: InterviewDifficulty;
  questionText: string;
  targetRequirementId?: string;
  reason: string;
  resumeProbe?: { skills: string[]; project?: { name: string; role?: string } };
  evidenceSource: { datasetId: string; documentName: string; source: string; sourceDate: string; qualityScore: number };
  referenceAnswer: string;
  coding?: BankCodingSpec;
}

const ev = (datasetId: string, documentName: string) => ({
  datasetId,
  documentName,
  source: `${documentName}#要点`,
  sourceDate: '2026-06-20',
  qualityScore: 0.92,
});

export const questionBank: BankQuestion[] = [
  {
    id: 'q_go_gmp',
    category: 'baguwen',
    topic: 'go-concurrency',
    questionType: 'theory',
    difficulty: 'medium',
    questionText:
      '请描述 Go 的 GMP 调度模型，并说明在什么情况下 goroutine 会发生调度切换？结合一个你项目中的并发场景说明选择。',
    targetRequirementId: 'req_01',
    reason: 'JD 第一优先必备项「Go 并发模型」；简历自述为 proficient，需要高密度追问验证。',
    resumeProbe: { skills: ['Go 并发编程'] },
    evidenceSource: ev('ds_fundamentals', 'Go 语言并发模型要点.md'),
    referenceAnswer:
      'GMP：G 为 goroutine，M 为操作系统线程，P 为本地调度器（持有 G 队列）。调度切换发生在：系统调用阻塞、channel 阻塞、抢占式调度（10ms 定时器）、gc、手工 Gosched。项目中的例子：用 goroutine+channel 做召回并行的扇出/扇入。',
  },
  {
    id: 'q_go_memmodel',
    category: 'baguwen',
    topic: 'go-concurrency',
    questionType: 'theory',
    difficulty: 'advanced',
    questionText:
      '简历中自述“深入理解 Go 内存模型”。请解释什么是 happens-before，并举例说明为什么两个 goroutine 直接读写共享变量需要同步。',
    targetRequirementId: 'req_01',
    reason: '针对高风险声明「深入理解 Go 内存模型」，验证是否只是名词熟悉。',
    resumeProbe: { skills: ['Go 并发编程'] },
    evidenceSource: ev('ds_fundamentals', 'Go 内存模型.md'),
    referenceAnswer:
      'happens-before 定义了共享内存写对读可见的偏序。同一 goroutine 顺序、channel 收发、锁加解锁、sync/atomic 操作都建立 happens-before。直接读写没有同步则数据竞争，结果不确定。',
  },
  {
    id: 'q_mysql_index',
    category: 'baguwen',
    topic: 'mysql',
    questionType: 'theory',
    difficulty: 'medium',
    questionText:
      '请说明联合索引的最左前缀原则，并解释覆盖索引为什么能避免回表。给出一个实际建索引的建议。',
    targetRequirementId: 'req_02',
    reason: '验证 JD「MySQL 索引原理」，覆盖简历声明中的索引优化。',
    resumeProbe: { skills: ['MySQL 数据库'] },
    evidenceSource: ev('ds_fundamentals', 'MySQL 索引原理.md'),
    referenceAnswer:
      '最左前缀：查询条件需从联合索引最左列开始连续匹配。覆盖索引是查询的列都包含在索引中，可省去回表随机 IO。建议：高基数列在前，避免在索引列上用函数。',
  },
  {
    id: 'q_mysql_txn',
    category: 'baguwen',
    topic: 'mysql',
    questionType: 'theory',
    difficulty: 'medium',
    questionText:
      'MySQL 默认隔离级别是什么？请解释 MVCC 如何实现可重复读，以及幻读在什么场景仍会出现。',
    targetRequirementId: 'req_02',
    reason: '验证 JD「事务隔离级别」。',
    resumeProbe: { skills: ['MySQL 数据库'] },
    evidenceSource: ev('ds_fundamentals', 'MySQL 事务隔离与 MVCC.md'),
    referenceAnswer:
      'InnoDB 默认 RR。MVCC 通过 undo log 版本链 + 一致性视图实现快照读；当前读仍会加间隙锁。快照读在 RR 下可避免幻读，当前读需要临键锁。',
  },
  {
    id: 'q_redis_penetration',
    category: 'baguwen',
    topic: 'redis',
    questionType: 'theory',
    difficulty: 'medium',
    questionText:
      '什么是缓存穿透、缓存击穿与缓存雪崩？结合简历中 RAG 系统的召回缓存，说明你分别采取了什么方案。',
    targetRequirementId: 'req_03',
    reason: '验证 JD「Redis 缓存工程化」，并直接追问项目中的真实落地。',
    resumeProbe: { skills: ['Redis 缓存'], project: { name: '基于 RAG 的智能面试系统', role: '后端负责人' } },
    evidenceSource: ev('ds_interview', '缓存问题高频面试题.md'),
    referenceAnswer:
      '穿透：查不到的数据打穿到 DB，用布隆过滤器 + 空值缓存。击穿：热点 key 失效瞬间，用互斥锁重建缓存。雪崩：大批 key 同时失效，用随机过期时间 + 多级缓存。项目中对召回结果做了分层缓存与重建锁。',
  },
  {
    id: 'q_redis_lock',
    category: 'interview_experience',
    topic: 'redis',
    questionType: 'scenario',
    difficulty: 'advanced',
    questionText:
      '简历中声称“熟练使用 Redis 分布式锁解决缓存一致性”。请设计一个可用的分布式锁：如何保证锁释放的原子性？如果持有锁的节点宕机了怎么办？锁过期但业务未执行完呢？',
    targetRequirementId: 'req_03',
    reason: '针对高风险声明「Redis 分布式锁」，考察锁的边界条件与 Redlock 争议。',
    resumeProbe: { skills: ['Redis 缓存'] },
    evidenceSource: ev('ds_interview', 'Redis 分布式锁.md'),
    referenceAnswer:
      '用 SET key value NX EX ttl 获取，Lua 脚本比对 value 后删除保证原子释放；宕机靠 TTL 兜底；锁过期未执行完用续期（看门狗）或在临界区内校验。',
  },
  {
    id: 'q_kafka_storm',
    category: 'interview_experience',
    topic: 'kafka',
    questionType: 'scenario',
    difficulty: 'medium',
    questionText:
      '线上 Kafka 消费堆积如何排查与处理？请结合简历中“主导 Kafka 消费者稳定性治理”说明你实际做了哪些措施。',
    targetRequirementId: 'req_04',
    reason: '针对高风险声明「主导 Kafka 消费者稳定性治理」，验证治理措施的深度。',
    resumeProbe: { skills: ['Kafka 消息队列'] },
    evidenceSource: ev('ds_interview', 'Kafka 消费堆积实战.md'),
    referenceAnswer:
      '先看 lag：分区数 × 消费速率估算堆积时间；原因可能是消费端耗时、分区数不足或 rebalance 频繁。措施：扩容分区/消费者、批量拉取、关闭不必要的事务、业务削峰。',
  },
  {
    id: 'q_kafka_semantics',
    category: 'interview_experience',
    topic: 'kafka',
    questionType: 'scenario',
    difficulty: 'advanced',
    questionText:
      '请解释 Kafka 的 at-least-once 与 exactly-once 语义。幂等生产者与事务能解决什么，不能解决什么？',
    targetRequirementId: 'req_04',
    reason: '验证 JD「Kafka 消息语义」，区分名词背诵与真实理解。',
    resumeProbe: { skills: ['Kafka 消息队列'] },
    evidenceSource: ev('ds_fundamentals', 'Kafka 消息语义.md'),
    referenceAnswer:
      '默认 at-least-once：重复消费靠幂等处理。exactly-once 需事务 + 幂等生产者，保证写入分区的原子性；跨系统的端到端精确一次仍需业务侧幂等。',
  },
  {
    id: 'q_sys_seckill',
    category: 'interview_experience',
    topic: 'system-design',
    questionType: 'scenario',
    difficulty: 'advanced',
    questionText:
      '请设计一个秒杀系统：如何在入口削峰、防止超卖，并保证缓存与数据库的一致性？画出大致链路。',
    targetRequirementId: 'req_05',
    reason: '验证 JD「系统设计与高并发架构」，校招候选人常见薄弱项。',
    resumeProbe: { skills: ['系统设计'] },
    evidenceSource: ev('ds_interview', '秒杀系统设计.md'),
    referenceAnswer:
      '前端限流 + 网关令牌桶，MQ 削峰，Redis 预扣库存 + Lua 原子扣减防超卖，DB 兜底对账；缓存一致性用延迟双删或订阅 binlog。',
  },
  {
    id: 'q_sys_cache_consistency',
    category: 'interview_experience',
    topic: 'system-design',
    questionType: 'scenario',
    difficulty: 'medium',
    questionText:
      '缓存与数据库的一致性方案有哪些？请比较 Cache Aside、Read Through 与延迟双删的适用场景。',
    targetRequirementId: 'req_05',
    reason: '验证 JD「缓存一致性」，与项目中的 Redis 缓存声明联动。',
    resumeProbe: { skills: ['Redis 缓存'] },
    evidenceSource: ev('ds_interview', '缓存一致性方案.md'),
    referenceAnswer:
      'Cache Aside 是主流：读未命中回源并回填，写先更新 DB 再删缓存；延迟双删缓解删缓存失败窗口；强一致场景用 binlog 订阅或写直通。',
  },
  {
    id: 'q_net_http',
    category: 'baguwen',
    topic: 'network',
    questionType: 'theory',
    difficulty: 'beginner',
    questionText:
      '常见的 HTTP 状态码有哪些？请解释幂等请求在支付场景中的意义，以及如何用消息队列保证不重复扣款。',
    targetRequirementId: 'req_06',
    reason: '验证 JD「HTTP/TCP 基础与幂等」。',
    resumeProbe: { skills: ['RAG 系统开发'] },
    evidenceSource: ev('ds_fundamentals', 'HTTP 基础.md'),
    referenceAnswer:
      '2xx 成功、3xx 重定向、4xx 客户端错误、5xx 服务端错误。幂等：同一请求重复执行结果一致；支付用幂等键 + 状态机去重，或 MQ 消费端做去重。',
  },
  {
    id: 'q_coding_ratelimit',
    category: 'leetcode',
    topic: 'algorithms',
    questionType: 'coding',
    difficulty: 'medium',
    questionText:
      '实现一个并发安全的令牌桶限流器：支持初始化容量与补充速率，提供 Allow() 判断是否放行。请关注并发安全与竞态。',
    targetRequirementId: 'req_01',
    reason: '算法题：把「Go 并发」落到可运行代码上，检验锁与原子操作的实际使用。',
    resumeProbe: { skills: ['Go 并发编程'] },
    evidenceSource: ev('ds_leetcode', '并发限流器.md'),
    referenceAnswer:
      '结构体包含 capacity、tokens、rate、last 与 sync.Mutex。Allow() 加锁后按 now.Sub(last) 补充令牌，tokens 足够则扣减返回 true，否则返回 false。并发安全由互斥锁保证。',
    coding: {
      language: 'go',
      starterCode:
        'package main\n\nimport "time"\n\ntype TokenBucket struct {\n\t// 请补全字段\n}\n\nfunc NewTokenBucket(capacity float64, refillPerSec float64) *TokenBucket {\n\treturn &TokenBucket{}\n}\n\n// Allow 判断是否放行一个请求\nfunc (b *TokenBucket) Allow() bool {\n\treturn false\n}\n',
      visibleTests: [
        { name: '容量内放行', input: 'capacity=5, 前5次', expected: '前5次全部放行' },
        { name: '超容拒绝', input: '连续请求6次', expected: '第6次被拒绝' },
        { name: '并发安全', input: '100 goroutine 并发', expected: '总放行数不超过容量' },
        { name: '按速率补充', input: '等待 refill 后放行', expected: '补充后恢复放行' },
      ],
      hiddenTotal: 5,
      hint: '用互斥锁保护令牌数，补充速率按当前时间差计算。',
    },
  },
  {
    id: 'q_coding_lru',
    category: 'leetcode',
    topic: 'algorithms',
    questionType: 'coding',
    difficulty: 'medium',
    questionText:
      '实现一个 LRU Cache（Get / Put，容量固定）。要求 Get 与 Put 平均 O(1)，考虑并发安全。',
    targetRequirementId: 'req_05',
    reason: '算法题：考察数据结构与工程健壮性。',
    resumeProbe: { skills: ['Go 并发编程'] },
    evidenceSource: ev('ds_leetcode', 'LRU Cache.md'),
    referenceAnswer:
      'map + container/list 双向链表。Get 命中后把节点移到链表头并返回；Put 更新或插入，插入时若超容量则淘汰链表尾节点并删除 map 键。O(1) 由哈希表与双向链表保证。',
    coding: {
      language: 'go',
      starterCode:
        'package main\n\ntype LRUCache struct {\n\t// 请补全\n}\n\nfunc NewLRUCache(capacity int) *LRUCache {\n\treturn &LRUCache{}\n}\n\nfunc (c *LRUCache) Get(key int) int {\n\treturn -1\n}\n\nfunc (c *LRUCache) Put(key int, value int) {\n}\n',
      visibleTests: [
        { name: '基本读写', input: 'Put(1,1); Get(1)', expected: '返回 1' },
        { name: '容量淘汰', input: '容量2, 写入3个', expected: '最久未用被淘汰' },
        { name: '访问刷新', input: 'Get 后调整顺序', expected: '被访问项不被淘汰' },
        { name: '覆盖更新', input: 'Put 已存在 key', expected: '更新值并刷新顺序' },
      ],
      hiddenTotal: 5,
      hint: '哈希表 + 双向链表，Go 中可用 container/list 与 map 组合。',
    },
  },
];

/* ---------------- 已完成演示面试 ---------------- */
type RoundPartial = Omit<InterviewRound, 'id' | 'sessionId' | 'sequence' | 'questionText' | 'evidenceSources'>;

const mkRound = (
  partial: RoundPartial,
  sessionId: string,
  sequence: number,
): InterviewRound => {
  const bank = questionBank.find((q) => q.id === partial.questionId)!;
  const defaults: Partial<InterviewRound> = {
    id: `round_${sessionId}_${sequence}`,
    sessionId,
    sequence,
    questionText: bank.questionText,
    candidateAnswers: [],
    followupQuestions: [],
    followupCount: 0,
    evidenceSources: [
      {
        evidenceId: `ev_${bank.id}`,
        datasetId: bank.evidenceSource.datasetId,
        documentName: bank.evidenceSource.documentName,
        source: bank.evidenceSource.source,
        sourceDate: bank.evidenceSource.sourceDate,
        qualityScore: bank.evidenceSource.qualityScore,
      },
    ],
  };
  return { ...defaults, ...partial } as InterviewRound;
};

export const demoSessionCompletedRounds: InterviewRound[] = [
  mkRound(
    {
      questionId: 'q_go_gmp',
      category: 'baguwen',
      topic: 'go-concurrency',
      questionType: 'theory',
      difficulty: 'medium',
      status: 'evaluated',
      targetRequirementId: 'req_01',
      targetTopic: 'go-concurrency',
      questionReason:
        'JD 第一必备项「Go 并发模型」；简历自述 proficient，需要高密度追问验证。',
      resumeProbe: { skills: ['Go 并发编程'] },
      initialScore: 3.2,
      score: 4.1,
      verdict: 'pass',
      judgeConfidence: 0.86,
      weakPoint: '对调度切换触发条件列举不完整',
      feedback:
        '整体正确：能说出 GMP 三层结构与 channel 通信。追问后补充了抢占式调度与系统调用阻塞两个关键切换点，达到合格线。',
      evaluationSummary: '初始 3.2 → 追问后 4.1（修正）',
      candidateAnswers: [
        {
          kind: 'initial',
          answer:
            'GMP 中 G 是 goroutine，M 是线程，P 是处理器队列。调度切换发生在 goroutine 让出时，比如 channel 阻塞或锁等待。项目里我用 goroutine 并发做召回，通过 channel 汇总结果。',
          submittedAt: '2026-08-09T15:04:00.000Z',
          evaluation: { score: 3.2, verdict: 'partial', feedback: '框架正确，但遗漏抢占式调度与系统调用场景。' },
        },
        {
          kind: 'followup',
          answer:
            '还有两类切换：一是系统调用或 IO 阻塞时，M 会挂起而 P 会绑定新 M 继续执行；二是 Go 的抢占式调度，超过 10ms 会被强制让出。GOMAXPROCS 决定同时运行的 P 数量。',
          submittedAt: '2026-08-09T15:06:00.000Z',
          evaluation: { score: 4.1, verdict: 'pass', feedback: '补充了关键切换点，理解到位。' },
        },
      ],
      followupQuestions: [
        {
          sequence: 1,
          question:
            '什么是 GOMAXPROCS？如果把它设置为 1，程序会出现什么行为？如何用实验证明你的结论？',
          selectedAction: 'followup',
          reason: '初始回答缺少抢占式与 IO 场景，继续深挖。',
          askedAt: '2026-08-09T15:05:00.000Z',
        },
      ],
      followupCount: 1,
    },
    IDS.sessionCompleted,
    1,
  ),
  mkRound(
    {
      questionId: 'q_mysql_index',
      category: 'baguwen',
      topic: 'mysql',
      questionType: 'theory',
      difficulty: 'medium',
      status: 'evaluated',
      targetRequirementId: 'req_02',
      targetTopic: 'mysql',
      questionReason: '验证 JD「MySQL 索引原理」，覆盖简历中的索引优化声明。',
      resumeProbe: { skills: ['MySQL 数据库'] },
      initialScore: 4.0,
      score: 4.0,
      verdict: 'pass',
      judgeConfidence: 0.9,
      weakPoint: '未主动提到索引下推（ICP）',
      feedback: '最左前缀与覆盖索引解释清晰，举例合理。该能力已获得充分证据。',
      evaluationSummary: '初始 4.0 · 已证明',
      candidateAnswers: [
        {
          kind: 'initial',
          answer:
            '最左前缀要求查询条件从联合索引第一列开始连续匹配，跳列会导致后面的列无法走索引。覆盖索引是 SELECT 的字段都在索引里，无需回表。比如给 (tenant_id, created_at) 建索引，按租户查时间区间能直接覆盖。',
          submittedAt: '2026-08-09T15:10:00.000Z',
          evaluation: { score: 4.0, verdict: 'pass', feedback: '概念准确且有场景示例。' },
        },
      ],
      followupQuestions: [],
      followupCount: 0,
    },
    IDS.sessionCompleted,
    2,
  ),
  mkRound(
    {
      questionId: 'q_redis_penetration',
      category: 'baguwen',
      topic: 'redis',
      questionType: 'theory',
      difficulty: 'medium',
      status: 'evaluated',
      targetRequirementId: 'req_03',
      targetTopic: 'redis',
      questionReason: '验证 JD「缓存工程化」，并直接追问项目落地。',
      resumeProbe: { skills: ['Redis 缓存'], project: { name: '基于 RAG 的智能面试系统', role: '后端负责人' } },
      initialScore: 2.6,
      score: 3.6,
      verdict: 'partial',
      judgeConfidence: 0.82,
      weakPoint: '缓存穿透的空值缓存与布隆过滤器混淆',
      feedback:
        '能说出三种问题的定义，但穿透方案细节含混（把空值缓存与布隆过滤器的取舍讲反了），追问后修正。结论：证据不足，建议补强。',
      evaluationSummary: '初始 2.6 → 追问后 3.6（证据不足）',
      candidateAnswers: [
        {
          kind: 'initial',
          answer:
            '穿透是查 DB 也没有，会反复打 DB；击穿是热点 key 过期瞬间；雪崩是大批 key 同时过期。我的方案是加布隆过滤器拦截空 key，热点数据用互斥锁防止击穿，过期时间加随机值防止雪崩。',
          submittedAt: '2026-08-09T15:14:00.000Z',
          evaluation: { score: 2.6, verdict: 'partial', feedback: '穿透处理理解有偏差：布隆过滤器挡的是不存在数据，空值缓存才是常用手段。' },
        },
        {
          kind: 'followup',
          answer:
            '对，我重新说：穿透时给不存在的 key 缓存空值并设置短 TTL，同时用布隆过滤器做前置判断减少空缓存数量；击穿用互斥锁重建；雪崩用随机 TTL 和多级缓存。项目里召回缓存就用了空值缓存。',
          submittedAt: '2026-08-09T15:16:00.000Z',
          evaluation: { score: 3.6, verdict: 'partial', feedback: '修正后方案正确，但项目细节仍偏少，未完全证明“熟练”。' },
        },
      ],
      followupQuestions: [
        {
          sequence: 1,
          question:
            '你说项目里加了布隆过滤器，请具体说明：布隆过滤器挡的是什么请求？和空值缓存的适用场景有什么差别？',
          selectedAction: 'followup',
          reason: '穿透方案细节含混，需要区分两种手段的边界。',
          askedAt: '2026-08-09T15:15:00.000Z',
        },
      ],
      followupCount: 1,
    },
    IDS.sessionCompleted,
    3,
  ),
  mkRound(
    {
      questionId: 'q_kafka_semantics',
      category: 'interview_experience',
      topic: 'kafka',
      questionType: 'scenario',
      difficulty: 'advanced',
      status: 'evaluated',
      targetRequirementId: 'req_04',
      targetTopic: 'kafka',
      questionReason: '针对高风险声明「主导 Kafka 消费者稳定性治理」，验证消息语义理解深度。',
      resumeProbe: { skills: ['Kafka 消息队列'] },
      initialScore: 3.0,
      score: 3.8,
      verdict: 'disputed',
      judgeConfidence: 0.78,
      weakPoint: '把 at-least-once 与 exactly-once 混淆',
      feedback:
        '初答把“at-least-once”讲成“每条只投递一次”，与 Kafka 语义不符，与简历声明“深入理解”存在矛盾；追问修正后恢复基本理解。该声明存在矛盾，需专项补强。',
      evaluationSummary: '初始 3.0 → 追问后 3.8（存在矛盾）',
      candidateAnswers: [
        {
          kind: 'initial',
          answer:
            'at-least-once 是消费者消费成功后提交位移，保证每条消息至少投递一次，所以不会有丢失；exactly-once 需要事务和幂等生产者，在读取-处理-写入链路中保证只写一次。我在项目里用 Kafka 做了面试题的异步评估。',
          submittedAt: '2026-08-09T15:20:00.000Z',
          evaluation: { score: 3.0, verdict: 'partial', feedback: '对 at-least-once 的理解有误（不是“保证至少投递一次=不丢”那么简单，重点是可能重复）。' },
        },
        {
          kind: 'followup',
          answer:
            '更正：at-least-once 的关键是可能重复消费，需要消费端幂等；exactly-once 结合幂等生产者只能保证写入 Kafka 分区内不重复，跨系统的端到端精确一次仍要靠业务去重。项目里评估结果表用了唯一约束做幂等。',
          submittedAt: '2026-08-09T15:22:00.000Z',
          evaluation: { score: 3.8, verdict: 'partial', feedback: '修正后基本正确，但“主导稳定性治理”的治理细节仍未体现。' },
        },
      ],
      followupQuestions: [
        {
          sequence: 1,
          question:
            '请区分 at-least-once 与 exactly-once。幂等生产者 + 事务能保证端到端精确一次吗？为什么？',
          selectedAction: 'followup',
          reason: '语义表述错误，需验证是否真正理解。',
          askedAt: '2026-08-09T15:21:00.000Z',
        },
      ],
      followupCount: 1,
    },
    IDS.sessionCompleted,
    4,
  ),
  mkRound(
    {
      questionId: 'q_coding_ratelimit',
      category: 'leetcode',
      topic: 'algorithms',
      questionType: 'coding',
      difficulty: 'medium',
      status: 'evaluated',
      targetRequirementId: 'req_01',
      targetTopic: 'algorithms',
      questionReason: '算法题：把「Go 并发」落到可运行代码上，检验锁与原子操作。',
      resumeProbe: { skills: ['Go 并发编程'] },
      codeSubmissionId: IDS.submission,
      initialScore: 3.0,
      score: 3.4,
      verdict: 'partial',
      judgeConfidence: 0.8,
      weakPoint: '初次未加锁，存在竞态；修正后通过',
      feedback:
        '首版实现没有加互斥锁，并发测试失败（4/4 中 2 项未过）；指出后补充 sync.Mutex 并基于时间差补充令牌，全部通过。工程习惯需加强：并发题先谈锁。',
      evaluationSummary: '首版并发失败 → 修正后通过（3.4）',
      candidateAnswers: [
        {
          kind: 'initial',
          answer: '（代码首版：未加锁，令牌计算在 Allow 内直接读写字段。）运行可见样例：2/4 通过，并发项失败。',
          submittedAt: '2026-08-09T15:26:00.000Z',
          evaluation: { score: 3.0, verdict: 'partial', feedback: '未考虑并发安全，竞态导致测试失败。' },
        },
        {
          kind: 'followup',
          answer: '（修正版：Allow 内加 sync.Mutex，按 now-last 时间差补充令牌，再扣减。）运行可见样例：4/4 通过；隐藏样例 5/5 通过。',
          submittedAt: '2026-08-09T15:30:00.000Z',
          evaluation: { score: 3.4, verdict: 'partial', feedback: '修正后正确，但应一开始就声明并发设计。' },
        },
      ],
      followupQuestions: [
        {
          sequence: 1,
          question:
            '并发测试失败了。请说明竞态发生在哪里，并给出加锁后的正确实现。',
          selectedAction: 'followup',
          reason: '代码存在数据竞争。',
          askedAt: '2026-08-09T15:28:00.000Z',
        },
      ],
      followupCount: 1,
    },
    IDS.sessionCompleted,
    5,
  ),
  mkRound(
    {
      questionId: 'q_sys_seckill',
      category: 'interview_experience',
      topic: 'system-design',
      questionType: 'scenario',
      difficulty: 'advanced',
      status: 'evaluated',
      targetRequirementId: 'req_05',
      targetTopic: 'system-design',
      questionReason: '验证 JD「系统设计与高并发架构」，校招候选人常见薄弱项。',
      resumeProbe: { skills: ['系统设计'] },
      initialScore: 3.0,
      score: 3.0,
      verdict: 'fail',
      judgeConfidence: 0.76,
      weakPoint: '削峰链路完整但防超卖与一致性方案缺失',
      feedback:
        '能说出入口限流与 MQ 削峰，但回答“扣库存用 Redis DECR 就行”，未覆盖 Lua 原子扣减、库存预扣与 DB 兜底，也未说明缓存一致性。证据不足，需系统补强。',
      evaluationSummary: '3.0 · 证据不足',
      candidateAnswers: [
        {
          kind: 'initial',
          answer:
            '秒杀一般是前端限流、网关限流，再把请求打进消息队列异步处理；扣库存我用 Redis DECR 快速扣，返回成功就下单。这样能扛住流量。',
          submittedAt: '2026-08-09T15:36:00.000Z',
          evaluation: { score: 3.0, verdict: 'fail', feedback: '扣库存方案有超卖风险：DECR 需要配合 Lua 原子判断；缺少 DB 兜底与对账。' },
        },
      ],
      followupQuestions: [],
      followupCount: 0,
    },
    IDS.sessionCompleted,
    6,
  ),
];

export const demoSubmission: CodeSubmission = {
  id: IDS.submission,
  sessionId: IDS.sessionCompleted,
  roundId: 'round_ses_demo_completed_01_5',
  language: 'go',
  executionStatus: 'completed',
  visibleTestResults: [
    { index: 0, status: 'pass', passed: true, actual: 'ok', expected: 'ok', runtimeMs: 3 },
    { index: 1, status: 'pass', passed: true, actual: 'denied', expected: 'denied', runtimeMs: 2 },
    { index: 2, status: 'pass', passed: true, actual: 'ok', expected: 'ok', runtimeMs: 4 },
    { index: 3, status: 'pass', passed: true, actual: 'ok', expected: 'ok', runtimeMs: 3 },
  ],
  hiddenTestSummary: { status: 'passed', passedCount: 5, totalCount: 5 },
  passedCount: 4,
  totalCount: 4,
  runtimeMs: 12,
  memoryKb: 1248,
  compilerOutput: 'ok',
};

export const demoJdMatrix = [
  {
    requirementId: 'req_01',
    requirementText: '熟练掌握 Go 语言核心，理解并发模型（GMP）、内存模型与 GC 机制',
    category: 'must_have' as const,
    weight: 0.9,
    resumeClaimStatus: 'matched' as const,
    resumeEvidence: [{ claim: 'Go 并发编程 · proficient' }],
    actualQuestions: [
      { roundId: 'round_ses_demo_completed_01_1', questionId: 'q_go_gmp', questionText: '请描述 Go 的 GMP 调度模型…', topic: 'go-concurrency' },
      { roundId: 'round_ses_demo_completed_01_5', questionId: 'q_coding_ratelimit', questionText: '实现一个并发安全的令牌桶限流器…', topic: 'algorithms' },
    ],
    score: 3.8,
    verificationStatus: 'verified' as const,
    supportEvidence: [
      { roundId: 'round_ses_demo_completed_01_1', questionId: 'q_go_gmp', evidenceIds: ['ev_q_go_gmp'], evidenceVersions: [], score: 4.1 },
      { roundId: 'round_ses_demo_completed_01_5', questionId: 'q_coding_ratelimit', evidenceIds: ['ev_q_coding_ratelimit'], evidenceVersions: [], score: 3.4 },
    ],
    improvementRecommendation: '并发模型理解达标；建议进一步准备 GC 原理与内存泄漏排查的追问。',
    unmapped: false,
  },
  {
    requirementId: 'req_02',
    requirementText: '熟悉 MySQL 索引原理与事务隔离级别，能定位并优化慢查询',
    category: 'must_have' as const,
    weight: 0.8,
    resumeClaimStatus: 'matched' as const,
    resumeEvidence: [{ claim: 'MySQL 数据库 · experienced' }],
    actualQuestions: [
      { roundId: 'round_ses_demo_completed_01_2', questionId: 'q_mysql_index', questionText: '请说明联合索引的最左前缀原则…', topic: 'mysql' },
    ],
    score: 4.0,
    verificationStatus: 'verified' as const,
    supportEvidence: [
      { roundId: 'round_ses_demo_completed_01_2', questionId: 'q_mysql_index', evidenceIds: ['ev_q_mysql_index'], evidenceVersions: [], score: 4.0 },
    ],
    improvementRecommendation: '索引部分已证明；建议补充事务隔离级别与 MVCC 细节。',
    unmapped: false,
  },
  {
    requirementId: 'req_03',
    requirementText: '熟悉 Redis 常见缓存问题（穿透/击穿/雪崩）并给出工程化方案',
    category: 'must_have' as const,
    weight: 0.8,
    resumeClaimStatus: 'matched' as const,
    resumeEvidence: [{ claim: 'Redis 缓存 · experienced' }],
    actualQuestions: [
      { roundId: 'round_ses_demo_completed_01_3', questionId: 'q_redis_penetration', questionText: '什么是缓存穿透、缓存击穿与缓存雪崩？…', topic: 'redis' },
    ],
    score: 3.6,
    verificationStatus: 'partial' as const,
    supportEvidence: [
      { roundId: 'round_ses_demo_completed_01_3', questionId: 'q_redis_penetration', evidenceIds: ['ev_q_redis_penetration'], evidenceVersions: [], score: 3.6 },
    ],
    improvementRecommendation: '空值缓存与布隆过滤器的边界需再巩固；建议用一次完整缓存面试题训练。',
    unmapped: false,
  },
  {
    requirementId: 'req_04',
    requirementText: '理解 Kafka 消息语义，能处理消费堆积与重平衡下的稳定性问题',
    category: 'must_have' as const,
    weight: 0.7,
    resumeClaimStatus: 'matched' as const,
    resumeEvidence: [{ claim: 'Kafka 消息队列 · familiar' }],
    actualQuestions: [
      { roundId: 'round_ses_demo_completed_01_4', questionId: 'q_kafka_semantics', questionText: '请解释 Kafka 的 at-least-once 与 exactly-once 语义…', topic: 'kafka' },
    ],
    score: 3.4,
    verificationStatus: 'disputed' as const,
    supportEvidence: [
      { roundId: 'round_ses_demo_completed_01_4', questionId: 'q_kafka_semantics', evidenceIds: ['ev_q_kafka_semantics'], evidenceVersions: [], score: 3.8 },
    ],
    improvementRecommendation: '与简历「主导稳定性治理」存在矛盾：建议先补消息语义，再准备重平衡与堆积治理细节。',
    unmapped: false,
  },
  {
    requirementId: 'req_05',
    requirementText: '具备分布式系统设计与高并发架构思路，能应对压测与容量规划',
    category: 'must_have' as const,
    weight: 0.9,
    resumeClaimStatus: 'missing' as const,
    resumeEvidence: [],
    actualQuestions: [
      { roundId: 'round_ses_demo_completed_01_6', questionId: 'q_sys_seckill', questionText: '请设计一个秒杀系统…', topic: 'system-design' },
    ],
    score: 3.0,
    verificationStatus: 'partial' as const,
    supportEvidence: [
      { roundId: 'round_ses_demo_completed_01_6', questionId: 'q_sys_seckill', evidenceIds: ['ev_q_sys_seckill'], evidenceVersions: [], score: 3.0 },
    ],
    improvementRecommendation: '简历未体现系统设计能力，实际答题也不足。列为下一场重点训练主题。',
    unmapped: false,
  },
  {
    requirementId: 'req_06',
    requirementText: '熟悉 HTTP/TCP 基础，能描述常见网络异常与幂等方案',
    category: 'must_have' as const,
    weight: 0.5,
    resumeClaimStatus: 'unknown' as const,
    resumeEvidence: [],
    actualQuestions: [],
    score: null,
    verificationStatus: 'untested' as const,
    supportEvidence: [],
    improvementRecommendation: '本轮未考察，建议下一场加入网络基础题验证。',
    unmapped: false,
  },
  {
    requirementId: 'req_07',
    requirementText: '了解 Docker 与 Kubernetes 基本部署与资源管理',
    category: 'nice_to_have' as const,
    weight: 0.3,
    resumeClaimStatus: 'missing' as const,
    resumeEvidence: [],
    actualQuestions: [],
    score: null,
    verificationStatus: 'untested' as const,
    supportEvidence: [],
    improvementRecommendation: '加分项未考察；简历也未声明，可不作为优先。',
    unmapped: false,
  },
];

export const demoReport: InterviewReport = {
  id: `rep_${IDS.sessionCompleted}`,
  sessionId: IDS.sessionCompleted,
  overallScore: 68,
  starRating: 3,
  abilityScores: {
    'Go 并发': 8.0,
    MySQL: 6.5,
    缓存: 6.0,
    Kafka: 5.4,
    系统设计: 4.2,
    算法: 6.6,
    网络: 5.0,
  },
  strengths: [
    { topic: 'Go 并发', score: 8.0 },
    { topic: 'MySQL 索引', score: 6.5 },
  ],
  weaknesses: [
    { topic: '系统设计', score: 4.2, priority: 1 },
    { topic: 'Kafka 消息语义', score: 5.4, priority: 2 },
    { topic: '缓存一致性', score: 6.0, priority: 3 },
  ],
  trainingPlan: [
    {
      order: 1,
      topic: '系统设计',
      action: '完成秒杀、短链、Feed 流三个常见设计的完整方案，重点是防超卖与缓存一致性。',
      successCriteria: '能独立画出链路并说清每个环节的取舍，2/3 题目达到 4 分以上。',
    },
    {
      order: 2,
      topic: 'Kafka 消息语义',
      action: '把 at-least-once / exactly-once / 幂等生产者 / 事务的边界整理成表格并口头复述。',
      successCriteria: '追问中不再混淆语义，能讲清端到端精确一次的边界。',
    },
    {
      order: 3,
      topic: '缓存一致性',
      action: '对比 Cache Aside / 延迟双删 / binlog 订阅，写出适用场景。',
      successCriteria: '能对“先删缓存还是先更 DB”给出明确结论并说明原因。',
    },
  ],
  metrics: {
    initialAnswerAverage: 3.4,
    postFollowupAverage: 3.7,
    difficultyScores: { medium: 3.8, advanced: 3.4 },
    categoryScores: { baguwen: 3.9, interview_experience: 3.4, leetcode: 3.4 },
    questionTypeScores: { theory: 4.0, scenario: 3.3, coding: 3.4 },
    followupCount: 4,
    questionCount: 6,
    recommendedRole: '中级 Go 后端开发',
    recommendedDifficulty: 'medium',
  },
  skillVerification: [
    { skill: 'Go 并发编程', claimedLevel: 'proficient', topics: ['GMP', '内存模型'], testedRoundCount: 2, avgScore: 3.8, status: 'verified', recommendation: '保持并发题手感，补充 GC 与内存泄漏排查。' },
    { skill: 'MySQL 数据库', claimedLevel: 'experienced', topics: ['索引'], testedRoundCount: 1, avgScore: 4.0, status: 'verified', recommendation: '补充事务隔离与 MVCC。' },
    { skill: 'Redis 缓存', claimedLevel: 'experienced', topics: ['缓存穿透', '分布式锁'], testedRoundCount: 1, avgScore: 3.6, status: 'partial', recommendation: '区分空值缓存与布隆过滤器边界。' },
    { skill: 'Kafka 消息队列', claimedLevel: 'familiar', topics: ['消息语义'], testedRoundCount: 1, avgScore: 3.8, status: 'disputed', recommendation: '简历声明“主导治理”与实际表现矛盾，先补消息语义。' },
    { skill: '系统设计', claimedLevel: 'beginner', topics: ['高并发'], testedRoundCount: 1, avgScore: 3.0, status: 'not_tested', recommendation: '作为下一场重点。' },
  ],
  jdVerificationMatrix: demoJdMatrix,
  reportMarkdown: `# 面试报告 · 中级 Go 后端开发

## 结论
- 目标岗位匹配度：68%（部分匹配）
- 已证明：Go 并发 / MySQL 索引；部分证明：Redis 缓存
- 声明矛盾：Kafka 消息语义与简历「主导稳定性治理」不一致
- 下一次重点：系统设计、Kafka 消息语义、缓存一致性

## 能力雷达
| 能力 | 分数 |
| --- | --- |
| Go 并发 | 8.0 |
| MySQL | 6.5 |
| 缓存 | 6.0 |
| Kafka | 5.4 |
| 系统设计 | 4.2 |
| 算法 | 6.6 |
| 网络 | 5.0 |

## 训练计划
1. 系统设计（秒杀/短链/Feed 流）
2. Kafka 消息语义
3. 缓存一致性`,
  reportVersion: '1.0',
};

export const demoSessionCompleted: InterviewSession = {
  id: IDS.sessionCompleted,
  profileId: IDS.profile,
  knowledgeConfigId: 'kc_01',
  status: 'completed',
  currentDifficulty: 'medium',
  maxQuestions: 6,
  maxFollowups: 2,
  completedQuestionCount: 6,
  currentRoundSequence: 6,
  stateVersion: 12,
  promptVersion: '1.0',
  plannerVersion: '1.0',
  job: { id: IDS.job, name: '中级 Go 后端开发工程师', unmappedRequirementIds: [] },
  startedAt: '2026-08-09T15:00:00.000Z',
  completedAt: '2026-08-09T15:42:00.000Z',
  createdAt: '2026-08-09T15:00:00.000Z',
  updatedAt: '2026-08-09T15:42:00.000Z',
  rounds: demoSessionCompletedRounds,
  report: demoReport,
};

/* ---------------- 进行中的演示面试（可继续） ---------------- */
export const demoSessionActive: InterviewSession = {
  id: IDS.sessionActive,
  profileId: IDS.profile,
  knowledgeConfigId: 'kc_01',
  status: 'awaiting_answer',
  currentDifficulty: 'medium',
  maxQuestions: 6,
  maxFollowups: 2,
  completedQuestionCount: 2,
  currentRoundSequence: 3,
  stateVersion: 5,
  promptVersion: '1.0',
  plannerVersion: '1.0',
  job: { id: IDS.job, name: '中级 Go 后端开发工程师', unmappedRequirementIds: [] },
  startedAt: '2026-08-10T10:00:00.000Z',
  createdAt: '2026-08-10T10:00:00.000Z',
  updatedAt: '2026-08-10T10:12:00.000Z',
  rounds: [
    mkRound(
      {
        questionId: 'q_mysql_txn',
        category: 'baguwen',
        topic: 'mysql',
        questionType: 'theory',
        difficulty: 'medium',
        status: 'evaluated',
        targetRequirementId: 'req_02',
        targetTopic: 'mysql',
        questionReason: '验证 JD「事务隔离级别」。',
        resumeProbe: { skills: ['MySQL 数据库'] },
        initialScore: 3.8,
        score: 3.8,
        verdict: 'pass',
        judgeConfidence: 0.88,
        weakPoint: '未展开当前读与间隙锁',
        feedback: 'MVCC 与可重复读解释正确。',
        evaluationSummary: '3.8 · 已证明',
        candidateAnswers: [
          {
            kind: 'initial',
            answer:
              'MySQL 默认 RR。MVCC 用版本链和 ReadView 实现快照读，RR 下事务内多次读结果一致；幻读在快照读下不出现，但当前读配合间隙锁处理。',
            submittedAt: '2026-08-10T10:03:00.000Z',
            evaluation: { score: 3.8, verdict: 'pass', feedback: '正确。' },
          },
        ],
        followupQuestions: [],
        followupCount: 0,
      },
      IDS.sessionActive,
      1,
    ),
    mkRound(
      {
        questionId: 'q_net_http',
        category: 'baguwen',
        topic: 'network',
        questionType: 'theory',
        difficulty: 'beginner',
        status: 'evaluated',
        targetRequirementId: 'req_06',
        targetTopic: 'network',
        questionReason: '验证 JD「网络与幂等」。',
        resumeProbe: { skills: ['RAG 系统开发'] },
        initialScore: 3.5,
        score: 3.5,
        verdict: 'pass',
        judgeConfidence: 0.84,
        weakPoint: '幂等键实现细节较少',
        feedback: '状态码分类正确。',
        evaluationSummary: '3.5 · 已证明',
        candidateAnswers: [
          {
            kind: 'initial',
            answer:
              '5xx 服务端异常要重试，4xx 客户端错误不重试。幂等用请求携带幂等键，服务端按键去重，保证重复请求不重复扣款。',
            submittedAt: '2026-08-10T10:09:00.000Z',
            evaluation: { score: 3.5, verdict: 'pass', feedback: '正确。' },
          },
        ],
        followupQuestions: [],
        followupCount: 0,
      },
      IDS.sessionActive,
      2,
    ),
  ],
};
