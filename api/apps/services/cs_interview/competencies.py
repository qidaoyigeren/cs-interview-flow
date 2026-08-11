"""Structured competency definitions, rubrics, anchor question groups and role policies.

This module is the single source of truth for *what an interview measures*. It is
pure and deterministic: no LLM calls, no database access. The production runtime
snapshots the resolved competency catalog into ``interview_session`` at creation
time and never re-reads this mutable catalog while a session runs.

A competency is the unit of *comparable* measurement:

* ``score_anchors`` map every score 0..4 to observable behavior that can be
  found in a candidate answer (never vague words like "较好"/"excellent").
* ``anchor_question_groups`` group questions that verify the same competency
  under the same rubric version, so different interviews stay comparable.
* ``RolePolicy`` lets each role tune weights, ratios and defaults without
  duplicating the runtime (planner / judge / report) code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from api.apps.services.cs_interview.domain import ROLE_CAPABILITY_TREES, Difficulty, topic_catalog

COMPETENCY_SNAPSHOT_VERSION = "cs-interview-competency-v2"
RUBRIC_VERSION = "cs-interview-rubric-v2"
MIN_ANCHOR_EVIDENCE = 1
HIGH_CONFIDENCE_THRESHOLD = 0.7
MUST_HAVE_ANCHOR_GUARD = "anchored"  # anchor_question_policy value meaning "must ask an anchor before adaptive follow-up"


@dataclass(frozen=True)
class ScoreAnchor:
    """Observable behavior that justifies one score level (0..4)."""

    level: int
    label: str
    observable_behavior: str
    indicators: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnchorQuestionGroup:
    """A set of equivalent questions verifying one competency under one rubric.

    All questions in the group validate the same competency and the same score
    anchors (``rubric_version``). Retrieval may pick any member; the score from
    any member is comparable across interviews because the rubric is shared.
    """

    anchor_group_id: str
    competency_id: str
    name: str
    topic_id: str
    difficulty: str
    content_type: str
    question_ids: tuple[str, ...] = ()
    rubric_version: str = RUBRIC_VERSION


@dataclass(frozen=True)
class CompetencySpec:
    competency_id: str
    role: str
    level: str
    name: str
    description: str
    weight: float
    must_have: bool
    observable_indicators: tuple[str, ...]
    allowed_evidence_types: tuple[str, ...]
    score_anchors: tuple[ScoreAnchor, ...]
    anchor_question_policy: str
    allowed_followup_directions: tuple[str, ...]
    stop_conditions: dict[str, Any]
    rubric_version: str = RUBRIC_VERSION


@dataclass(frozen=True)
class RolePolicy:
    role: str
    level: str
    key_competency_ids: tuple[str, ...]
    competency_weights: dict[str, float]
    anchor_group_ids: tuple[str, ...]
    allowed_followup_directions: tuple[str, ...]
    coding_question_ratio: float
    system_design_ratio: float
    communication_dimensions: tuple[str, ...]
    expected_duration_minutes: int
    default_difficulty: str


@dataclass(frozen=True)
class LevelPolicy:
    """Expected proficiency for a target seniority.

    Scores keep the same 0..4 meaning across levels so reports remain
    comparable.  Seniority changes the required score, evidence depth and
    default difficulty instead of silently redefining what a score means.
    """

    level: str
    required_score: int
    minimum_high_confidence_evidence: int
    default_difficulty: str
    expectation: str


LEVEL_POLICIES: dict[str, LevelPolicy] = {
    "junior": LevelPolicy("junior", 2, 1, Difficulty.BEGINNER.value, "正确说明核心概念，并能处理典型问题。"),
    "mid": LevelPolicy("mid", 3, 1, Difficulty.MEDIUM.value, "解释关键机制，结合场景说明方案与权衡。"),
    "senior": LevelPolicy("senior", 4, 1, Difficulty.ADVANCED.value, "覆盖失败模式、替代方案、系统边界与工程成本。"),
    "staff": LevelPolicy("staff", 4, 1, Difficulty.ADVANCED.value, "在高级工程判断上进一步说明组织级影响与长期演进成本。"),
}


def level_policy_for(level: str) -> LevelPolicy:
    """Resolve an explicit profile level; legacy ``all`` maps to mid-level."""

    return LEVEL_POLICIES.get(str(level).lower(), LEVEL_POLICIES["mid"])


# ---------------------------------------------------------------------------
# Observable indicators per competency.  Each topic in ROLE_CAPABILITY_TREES
# gets a competency.  Indicators are split into "typical" (level 2), "scenario
# + tradeoff" (level 3) and "boundary / failure / alternative / cost" (level 4)
# so that the generated score anchors always reference observable behavior.
# ---------------------------------------------------------------------------

_TOPIC_INDICATORS: dict[str, dict[str, tuple[str, ...]]] = {
    "ai.rag": {
        "typical": ("检索-增强-生成链路", "embedding 与 top-k", "引文/来源标注"),
        "scenario": ("块大小与召回权衡", "rerank 的作用", "上下文窗口溢出处理", "无答案查询处理"),
        "boundary": ("索引过期/权限隔离", "混合检索 vs 纯向量", "大模型幻觉与引用一致性", "索引更新与 rerank 成本"),
    },
    "ai.agent": {
        "typical": ("工具调用协议", "Agent 循环：规划-执行-观察", "终止条件"),
        "scenario": ("工具失败重试", "多工具编排", "权限边界"),
        "boundary": ("循环失控/预算约束", "工具幻觉选择", "与工作流引擎的取舍", "可观测性与回放成本"),
    },
    "ai.evaluation": {
        "typical": ("评测集构造", "离线/在线指标", "人工与自动评测"),
        "scenario": ("回答质量评测设计", "评测噪声控制", "回归门禁"),
        "boundary": ("测试集污染/数据泄漏", "指标与业务目标错位", "成本与覆盖率权衡", "标注一致性控制"),
    },
    "go.runtime": {
        "typical": ("goroutine 与 channel", "GMP 调度模型", "内存模型与 sync 原语"),
        "scenario": ("并发泄漏排查", "context 取消传播", "限流/超时控制"),
        "boundary": ("调度饥饿/锁竞争", "channel vs mutex 取舍", "GC 与延迟权衡", "pprof 定位成本"),
    },
    "database.mysql": {
        "typical": ("索引与 B+ 树", "事务 ACID 与隔离级别", "锁与 MVCC"),
        "scenario": ("慢查询优化", "死锁处理", "索引失效场景"),
        "boundary": ("隔离级别权衡", "分库分表 vs 单库", "主从延迟与一致性", "行锁升级与死锁成本"),
    },
    "database.core": {
        "typical": ("索引与执行计划", "事务与隔离", "基本 SQL 优化"),
        "scenario": ("慢查询诊断", "并发写冲突", "备份与恢复"),
        "boundary": ("分布式事务取舍", "读写分离一致性", "索引与写入放大成本", "CAP 边界"),
    },
    "java.jvm": {
        "typical": ("JVM 内存区域", "GC 算法与回收器", "类加载与双亲委派"),
        "scenario": ("OOM/泄漏排查", "GC 调优", "并发工具"),
        "boundary": ("G1/ZGC 取舍", "内存屏障与可见性", "动态编译/逃逸分析", "堆与元空间成本"),
    },
    "java.spring": {
        "typical": ("IoC/AOP 原理", "事务与传播行为", "Bean 生命周期"),
        "scenario": ("事务失效排查", "循环依赖处理", "配置化治理"),
        "boundary": ("代理机制边界", "微服务治理权衡", "事务嵌套成本", "框架升级兼容性"),
    },
    "python.runtime": {
        "typical": ("GIL 与线程", "asyncio 事件循环", "对象模型与内存管理"),
        "scenario": ("并发/异步改造", "性能剖析", "内存泄漏定位"),
        "boundary": ("GIL 取舍与替代", "同步/异步边界", "进程 vs 线程 vs 协程", "引用计数与循环引用成本"),
    },
    "python.web": {
        "typical": ("WSGI/ASGI 模型", "中间件与依赖注入", "数据库会话管理"),
        "scenario": ("异步服务限流", "请求级超时", "连接池调优"),
        "boundary": ("同步阻塞混用边界", "框架生态取舍", "并发模型成本", "安全头/输入校验"),
    },
    "backend.distributed": {
        "typical": ("一致性模型", "分布式事务", "消息队列可靠性"),
        "scenario": ("幂等设计", "缓存一致性", "链路超时与降级"),
        "boundary": ("分区容错取舍", "最终一致 vs 强一致", "分布式锁边界", "成本与复杂度权衡"),
    },
    "frontend.javascript": {
        "typical": ("事件循环与异步", "闭包/原型链", "DOM 与渲染机制"),
        "scenario": ("内存泄漏排查", "防抖节流", "长任务优化"),
        "boundary": ("宏/微任务边界", "immutable vs mutable", "SSR/CSR 取舍", "兼容性与包体积成本"),
    },
    "frontend.react": {
        "typical": ("渲染模型与协调", "hooks 规则", "状态管理"),
        "scenario": ("重渲染优化", "副作用管理", "列表性能"),
        "boundary": ("concurrent 模式边界", "状态库取舍", "memo 成本", "SSR 水合一致性"),
    },
    "frontend.performance": {
        "typical": ("关键渲染路径", "资源加载优化", "性能指标"),
        "scenario": ("首屏优化", "图片/字体优化", "性能预算"),
        "boundary": ("缓存策略权衡", "网络/渲染成本", "可访问性冲突", "观测与回归成本"),
    },
    "ml.fundamentals": {
        "typical": ("损失函数与优化", "过拟合与正则", "评估指标"),
        "scenario": ("模型选择", "样本不均衡", "特征工程"),
        "boundary": ("偏差方差权衡", "数据泄漏", "可解释性取舍", "训练成本"),
    },
    "ml.system": {
        "typical": ("训练/推理管线", "分布式训练", "模型服务"),
        "scenario": ("显存优化", "批处理/缓存", "弹性扩缩"),
        "boundary": ("成本与延迟权衡", "容错与检查点", "异构资源调度", "量化/蒸馏取舍"),
    },
    "ml.evaluation": {
        "typical": ("离线/在线指标", "评测集划分", "显著性检验"),
        "scenario": ("A/B 设计", "评测噪声控制", "回归门禁"),
        "boundary": ("泄漏与污染", "指标错位", "标注成本", "置信区间与样本量"),
    },
    "testing.strategy": {
        "typical": ("测试金字塔", "用例分层", "覆盖率与回归"),
        "scenario": ("测试计划设计", "缺陷聚类", "质量门禁"),
        "boundary": ("覆盖率欺骗", "自动化成本权衡", "稳定性 vs 覆盖率", "测试数据治理"),
    },
    "testing.automation": {
        "typical": ("自动化框架", "断言与等待", "数据驱动"),
        "scenario": ("不稳定用例治理", "并行执行", "报告集成"),
        "boundary": ("录制/脚本取舍", "维护成本", "环境隔离", "执行耗时预算"),
    },
    "testing.performance": {
        "typical": ("压测模型", "性能指标", "负载生成"),
        "scenario": ("瓶颈定位", "容量评估", "限流验证"),
        "boundary": ("压测失真", "资源成本", "峰值模型误差", "监控与复盘成本"),
    },
    "os.core": {
        "typical": ("进程/线程模型", "内存管理", "文件系统"),
        "scenario": ("死锁排查", "IO 模型", "上下文切换"),
        "boundary": ("虚拟内存边界", "内核态/用户态成本", "调度策略权衡", "缓存一致性"),
    },
    "network.core": {
        "typical": ("TCP/UDP", "HTTP 语义", "DNS/负载均衡"),
        "scenario": ("连接状态诊断", "超时重试", "安全传输"),
        "boundary": ("拥塞控制边界", "协议取舍", "NAT/代理成本", "端到端延迟分解"),
    },
    "algorithm.core": {
        "typical": ("复杂度分析", "常用数据结构", "经典算法"),
        "scenario": ("贪心/动态规划权衡", "图算法应用", "双指针/滑动窗口"),
        "boundary": ("最坏/均摊复杂度", "空间换时间成本", "边界输入与溢出", "算法与工程约束取舍"),
    },
}


def _indicators_for(topic_id: str) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    spec = _TOPIC_INDICATORS.get(topic_id)
    if spec is None:
        return ("核心概念与典型实现",), ("机制解释与场景权衡",), ("边界、失败模式、替代方案与工程成本",)
    return spec["typical"], spec["scenario"], spec["boundary"]


def _build_anchors(topic_id: str, name: str) -> tuple[ScoreAnchor, ...]:
    """Deterministic 0..4 anchors whose behavior is tied to the competency's indicators."""
    typical, scenario, boundary = _indicators_for(topic_id)
    return (
        ScoreAnchor(
            0,
            "无尝试",
            "空白、拒答、无关内容，或没有任何技术尝试。",
            ("无回答", "拒答", "无关内容"),
        ),
        ScoreAnchor(
            1,
            "有尝试但核心错误",
            "存在相关尝试，但核心事实或方案明显错误。",
            ("相关尝试", "核心事实错误", "方案不成立"),
        ),
        ScoreAnchor(
            2,
            "掌握基础",
            f"正确展示 {name} 的典型机制，能处理典型问题。",
            typical,
        ),
        ScoreAnchor(
            3,
            "机制+场景+权衡",
            "在 2 分基础上结合机制解释原因、应用于具体场景并说明权衡。",
            scenario,
        ),
        ScoreAnchor(
            4,
            "边界与工程分析",
            "在 3 分基础上分析边界情况、失败模式、替代方案与工程成本。",
            boundary,
        ),
    )


def build_competency_catalog() -> dict[str, tuple[CompetencySpec, ...]]:
    """Build the full competency catalog from ROLE_CAPABILITY_TREES.

    Every role/topic in the existing capability tree gets a competency so the
    runtime never loses a topic it could previously ask about.
    """
    catalog: dict[str, tuple[CompetencySpec, ...]] = {}
    for role, topics in ROLE_CAPABILITY_TREES.items():
        specs = []
        for topic in topics:
            typical, scenario, boundary = _indicators_for(topic.id)
            anchors = _build_anchors(topic.id, topic.name)
            must_have = topic.weight >= 1.2
            specs.append(
                CompetencySpec(
                    competency_id=topic.id,
                    role=role,
                    level="profile_resolved",
                    name=topic.name,
                    description=f"{role} 岗位下“{topic.name}”能力的结构化定义。",
                    weight=topic.weight,
                    must_have=must_have,
                    observable_indicators=(*typical, *scenario, *boundary),
                    allowed_evidence_types=("mechanism", "scenario", "tradeoff", "example", "failure_mode"),
                    score_anchors=anchors,
                    anchor_question_policy=MUST_HAVE_ANCHOR_GUARD if must_have else "adaptive_ok",
                    allowed_followup_directions=("boundary", "failure_mode", "alternative", "tradeoff"),
                    stop_conditions={
                        "min_anchor_evidence": MIN_ANCHOR_EVIDENCE,
                        "high_confidence_threshold": HIGH_CONFIDENCE_THRESHOLD,
                        "max_evidence_per_competency": 3,
                    },
                    rubric_version=RUBRIC_VERSION,
                )
            )
        catalog[role] = tuple(specs)
    return catalog


COMPETENCY_CATALOG = build_competency_catalog()


_ANCHOR_QUESTION_SPECS: dict[tuple[str, str], tuple[str, str, str]] = {
    # (role, competency) -> (question_id, content_type, difficulty).  These IDs
    # are also written into the reviewed knowledge manifest.  A must-have
    # competency without an explicit member is rejected during snapshot build;
    # anchor selection never falls back to an unrelated topic document.
    ("go_backend", "go.runtime"): ("public-fund-context-001", "fundamentals", "medium"),
    ("go_backend", "database.mysql"): ("public-mysql-slow-001", "interview_experience", "medium"),
    ("java_backend", "java.jvm"): ("scale-fund-java_jmm-001", "fundamentals", "medium"),
    ("java_backend", "java.spring"): ("scale-fund-spring_proxy-001", "fundamentals", "medium"),
    ("python_backend", "python.runtime"): ("scale-fund-python_memory-001", "fundamentals", "medium"),
    ("python_backend", "python.web"): ("scale-fund-python_event_loop-001", "fundamentals", "medium"),
    ("frontend", "frontend.javascript"): ("scale-inte-frontend_hydration-001", "interview_experience", "medium"),
    ("frontend", "frontend.react"): ("scale-fund-react_reconciliation-001", "fundamentals", "medium"),
    ("ml_engineer", "ml.fundamentals"): ("scale-fund-ml_regularization-001", "fundamentals", "medium"),
    ("ml_engineer", "ml.system"): ("scale-inte-ml_training_serving_skew-001", "interview_experience", "medium"),
    ("ai_backend", "ai.rag"): ("scale-fund-rag_chunking-001", "fundamentals", "medium"),
    ("ai_backend", "ai.agent"): ("public-agent-tool-reliability-001", "interview_experience", "medium"),
    ("sdet", "testing.strategy"): ("scale-inte-sdet_env_contamination-001", "interview_experience", "beginner"),
    ("sdet", "testing.automation"): ("scale-fund-property_testing-001", "fundamentals", "medium"),
}


def _role_anchor_group(role: str, competency: CompetencySpec) -> AnchorQuestionGroup:
    question = _ANCHOR_QUESTION_SPECS.get((role, competency.competency_id))
    question_ids = (question[0],) if question else ()
    content_type = question[1] if question else "fundamentals"
    difficulty = question[2] if question else Difficulty.MEDIUM.value
    return AnchorQuestionGroup(
        anchor_group_id=f"anchor-{role}-{competency.competency_id.replace('.', '-')}",
        competency_id=competency.competency_id,
        name=f"{role}:{competency.name} 锚点题组",
        topic_id=competency.competency_id,
        difficulty=difficulty,
        content_type=content_type,
        question_ids=question_ids,
        rubric_version=competency.rubric_version,
    )


def build_anchor_groups() -> dict[str, AnchorQuestionGroup]:
    groups: dict[str, AnchorQuestionGroup] = {}
    for role, specs in COMPETENCY_CATALOG.items():
        for competency in specs:
            group = _role_anchor_group(role, competency)
            if group.question_ids:
                groups[group.anchor_group_id] = group
    return groups


ANCHOR_GROUPS = build_anchor_groups()


def build_role_policies() -> dict[str, RolePolicy]:
    """Per-role interview policy.  The runtime executes ONE engine for every role."""
    policies: dict[str, RolePolicy] = {}
    coding_ratio_by_role = {
        "go_backend": 0.25,
        "java_backend": 0.25,
        "python_backend": 0.25,
        "frontend": 0.3,
        "ml_engineer": 0.25,
        "ai_backend": 0.25,
        "sdet": 0.2,
        "cs_general": 0.25,
    }
    for role, specs in COMPETENCY_CATALOG.items():
        key_competencies = tuple(spec.competency_id for spec in specs if spec.weight >= 1.1)
        weights = {spec.competency_id: spec.weight for spec in specs}
        anchor_group_ids = tuple(
            f"anchor-{role}-{spec.competency_id.replace('.', '-')}"
            for spec in specs
            if (role, spec.competency_id) in _ANCHOR_QUESTION_SPECS
        )
        policies[role] = RolePolicy(
            role=role,
            level="profile_resolved",
            key_competency_ids=key_competencies,
            competency_weights=weights,
            anchor_group_ids=anchor_group_ids,
            allowed_followup_directions=("boundary", "failure_mode", "alternative", "tradeoff"),
            coding_question_ratio=coding_ratio_by_role.get(role, 0.25),
            system_design_ratio=0.15,
            communication_dimensions=("clarity", "structure", "tradeoff_awareness"),
            expected_duration_minutes=45,
            default_difficulty=Difficulty.MEDIUM.value,
        )
    return policies


ROLE_POLICIES = build_role_policies()


# ---------------------------------------------------------------------------
# Validation and snapshot helpers
# ---------------------------------------------------------------------------


def validate_score_anchors(anchors: tuple[ScoreAnchor, ...]) -> list[str]:
    """A rubric must define exactly levels 0..4 with observable behavior."""
    errors: list[str] = []
    levels = sorted(anchor.level for anchor in anchors)
    if levels != [0, 1, 2, 3, 4]:
        errors.append("score_anchors must define exactly levels 0,1,2,3,4")
    seen_behavior = set()
    for anchor in anchors:
        if len(anchor.label) < 2 or len(anchor.observable_behavior) < 8:
            errors.append(f"score anchor {anchor.level} lacks a concrete observable behavior")
        if not anchor.indicators:
            errors.append(f"score anchor {anchor.level} has no observable indicators")
        if anchor.observable_behavior in seen_behavior:
            errors.append(f"score anchor {anchor.level} duplicates another level's behavior")
        seen_behavior.add(anchor.observable_behavior)
    return errors


def validate_competency_spec(spec: CompetencySpec) -> list[str]:
    errors = validate_score_anchors(spec.score_anchors)
    if not spec.competency_id or not spec.name or not spec.description:
        errors.append("competency requires id, name and description")
    if not 0 < spec.weight <= 2.0:
        errors.append("competency weight must be within (0, 2]")
    if spec.anchor_question_policy not in {"anchored", "adaptive_ok"}:
        errors.append("invalid anchor_question_policy")
    if not spec.observable_indicators:
        errors.append("competency requires observable indicators")
    if spec.competency_id not in topic_catalog():
        errors.append(f"competency {spec.competency_id} is not a known topic")
    return errors


def validate_rubric_snapshot(snapshot: dict[str, Any]) -> list[str]:
    """Validate a stored (immutable) rubric snapshot produced by build_rubric_snapshot."""
    errors: list[str] = []
    if not snapshot.get("rubric_version"):
        errors.append("rubric snapshot requires rubric_version")
    anchors = snapshot.get("score_anchors")
    if not isinstance(anchors, dict) or sorted(map(int, anchors)) != [0, 1, 2, 3, 4]:
        errors.append("rubric snapshot must define score anchors for 0..4")
    for level in range(5):
        entry = anchors.get(str(level)) or {}
        if not entry.get("observable_behavior"):
            errors.append(f"rubric snapshot anchor {level} lacks observable behavior")
    if not isinstance(snapshot.get("observable_indicators"), list) or not snapshot["observable_indicators"]:
        errors.append("rubric snapshot requires observable_indicators")
    return errors


def competency_for_topic(role: str, topic_id: str) -> CompetencySpec | None:
    for spec in COMPETENCY_CATALOG.get(role, ()):
        if spec.competency_id == topic_id:
            return spec
    for specs in COMPETENCY_CATALOG.values():
        for spec in specs:
            if spec.competency_id == topic_id:
                return spec
    return None


def role_policy_for(role: str) -> RolePolicy:
    policy = ROLE_POLICIES.get(role)
    if policy is not None:
        return policy
    # Every role in the capability tree has a policy; fall back to the first.
    return next(iter(ROLE_POLICIES.values()))


def build_rubric_snapshot(competency: CompetencySpec, level: str = "mid") -> dict[str, Any]:
    """Immutable rubric snapshot frozen into the session at creation time."""
    level_policy = level_policy_for(level)
    return {
        "competency_id": competency.competency_id,
        "name": competency.name,
        "rubric_version": competency.rubric_version,
        "target_level": level_policy.level,
        "required_score": level_policy.required_score,
        "minimum_high_confidence_evidence": level_policy.minimum_high_confidence_evidence,
        "level_expectation": level_policy.expectation,
        "observable_indicators": list(competency.observable_indicators),
        "allowed_evidence_types": list(competency.allowed_evidence_types),
        "score_anchors": {
            str(anchor.level): {
                "label": anchor.label,
                "observable_behavior": anchor.observable_behavior,
                "indicators": list(anchor.indicators),
            }
            for anchor in sorted(competency.score_anchors, key=lambda item: item.level)
        },
    }


def build_competency_snapshot(role: str, level: str = "all") -> dict[str, Any]:
    """Immutable competency + rubric snapshot stored on the session.

    The running session must only consult this snapshot (never the mutable
    catalog above), which is why both the spec and its rubric snapshot are
    embedded here.
    """
    specs = COMPETENCY_CATALOG.get(role)
    if not specs:
        raise ValueError(f"Unknown target role {role!r} for competency snapshot.")
    level_policy = level_policy_for(level)
    competencies = []
    rubrics: dict[str, dict[str, Any]] = {}
    for spec in specs:
        spec_dict = {
            "competency_id": spec.competency_id,
            "role": spec.role,
            "level": level_policy.level,
            "name": spec.name,
            "description": spec.description,
            "weight": spec.weight,
            "must_have": spec.must_have,
            "observable_indicators": list(spec.observable_indicators),
            "allowed_evidence_types": list(spec.allowed_evidence_types),
            "score_anchors": {
                str(anchor.level): {
                    "label": anchor.label,
                    "observable_behavior": anchor.observable_behavior,
                    "indicators": list(anchor.indicators),
                }
                for anchor in sorted(spec.score_anchors, key=lambda item: item.level)
            },
            "anchor_question_policy": spec.anchor_question_policy,
            "allowed_followup_directions": list(spec.allowed_followup_directions),
            "stop_conditions": dict(spec.stop_conditions),
            "required_score": level_policy.required_score,
            "minimum_high_confidence_evidence": level_policy.minimum_high_confidence_evidence,
            "level_expectation": level_policy.expectation,
            "rubric_version": spec.rubric_version,
        }
        competencies.append(spec_dict)
        rubrics[spec.competency_id] = build_rubric_snapshot(spec, level_policy.level)
    policy = role_policy_for(role)
    anchor_groups = {
        group.anchor_group_id: {
            "anchor_group_id": group.anchor_group_id,
            "competency_id": group.competency_id,
            "name": group.name,
            "topic_id": group.topic_id,
            "difficulty": group.difficulty,
            "content_type": group.content_type,
            "question_ids": list(group.question_ids),
            "rubric_version": group.rubric_version,
        }
        for group in ANCHOR_GROUPS.values()
        if group.anchor_group_id in policy.anchor_group_ids
    }
    return {
        "snapshot_version": COMPETENCY_SNAPSHOT_VERSION,
        "role": role,
        "level": level_policy.level,
        "rubric_version": RUBRIC_VERSION,
        "competencies": competencies,
        "rubrics": rubrics,
        "anchor_groups": anchor_groups,
        "role_policy": {
            "role": policy.role,
            "level": level_policy.level,
            "required_score": level_policy.required_score,
            "minimum_high_confidence_evidence": level_policy.minimum_high_confidence_evidence,
            "key_competency_ids": list(policy.key_competency_ids),
            "competency_weights": dict(policy.competency_weights),
            "allowed_followup_directions": list(policy.allowed_followup_directions),
            "coding_question_ratio": policy.coding_question_ratio,
            "system_design_ratio": policy.system_design_ratio,
            "communication_dimensions": list(policy.communication_dimensions),
            "expected_duration_minutes": policy.expected_duration_minutes,
            "default_difficulty": level_policy.default_difficulty,
            "level_expectation": level_policy.expectation,
        },
    }


def must_have_competency_ids(competency_snapshot: dict[str, Any]) -> list[str]:
    return [
        str(item["competency_id"])
        for item in (competency_snapshot.get("competencies") or [])
        if item.get("must_have")
    ]


def rubric_snapshot_for(competency_snapshot: dict[str, Any], competency_id: str) -> dict[str, Any] | None:
    rubrics = competency_snapshot.get("rubrics") or {}
    return rubrics.get(competency_id)


def anchor_group_for(competency_snapshot: dict[str, Any], competency_id: str) -> dict[str, Any] | None:
    for group in (competency_snapshot.get("anchor_groups") or {}).values():
        if group.get("competency_id") == competency_id:
            return group
    return None


def build_expected_evidence(competency_snapshot: dict[str, Any], competency_id: str) -> dict[str, Any]:
    """What a question on this competency is expected to elicit (internal only)."""
    rubric = rubric_snapshot_for(competency_snapshot, competency_id) or {}
    anchors = rubric.get("score_anchors") or {}
    return {
        "competency_id": competency_id,
        "target_level": int(rubric.get("required_score") or 3),
        "level": rubric.get("target_level") or competency_snapshot.get("level") or "mid",
        "level_expectation": rubric.get("level_expectation") or "",
        "target_indicators": list(rubric.get("observable_indicators") or []),
        "anchor_behavior": {level: (anchors.get(level) or {}).get("observable_behavior") for level in ("2", "3", "4")},
        "allowed_evidence_types": list(rubric.get("allowed_evidence_types") or []),
    }


def validate_competency_snapshot(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if snapshot.get("snapshot_version") != COMPETENCY_SNAPSHOT_VERSION:
        errors.append("competency snapshot has an unsupported version")
    competencies = snapshot.get("competencies")
    if not isinstance(competencies, list) or not competencies:
        errors.append("competency snapshot requires a non-empty competency list")
        return errors
    for item in competencies:
        anchors = item.get("score_anchors") or {}
        if sorted(map(int, anchors)) != [0, 1, 2, 3, 4]:
            errors.append(f"competency {item.get('competency_id')} score anchors must cover 0..4")
        required_score = item.get("required_score")
        if required_score not in {2, 3, 4}:
            errors.append(f"competency {item.get('competency_id')} has invalid required_score")
        if item.get("must_have"):
            group = anchor_group_for(snapshot, str(item.get("competency_id") or ""))
            if not group or not group.get("question_ids"):
                errors.append(f"must-have competency {item.get('competency_id')} requires a concrete anchor question")
    return errors


def normalize_competency_snapshot(role: str, level: str = "all") -> dict[str, Any]:
    """Build and validate the immutable snapshot before persisting it."""
    snapshot = build_competency_snapshot(role, level)
    errors = validate_competency_snapshot(snapshot)
    if errors:
        raise ValueError("Invalid competency snapshot: " + "; ".join(errors))
    return snapshot
