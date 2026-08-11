"""Pure domain rules for the CS interview application.

The functions in this module do not call an LLM and do not write to the
database.  Keeping state policy here makes every transition deterministic and
allows the production runtime and offline evaluator to share exactly the same
rules.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

PROMPT_VERSION = "cs-interview-v1"
REPORT_VERSION = "cs-interview-report-v5"
JOB_EXTRACTION_VERSION = "cs-interview-jd-extraction-v1"
ANSWER_STATE_VERSION = "cs-interview-answer-state-v4"
PLANNER_VERSION = "cs-interview-planner-v2"
# v2 resume extraction produces structured projects with per-project claims
# (evidence_span, claim_type, deterministic project_id/claim_id, risk flags).
# Old v1 extractions must be re-extracted before a new profile/session is made.
EXTRACTION_VERSION = "cs-interview-resume-extraction-v2"
ATTACK_MAP_VERSION = "cs-interview-project-attack-map-v1"
MAX_ANSWER_CHARS = 20_000
MAX_SOURCE_CHARS = 50_000
MAX_JOB_CHARS = 50_000
MAX_COMPILER_OUTPUT = 8_000
SUPPORTED_LANGUAGES = {"python", "go", "javascript"}
CLAIMED_LEVELS = {"fluent", "experienced", "proficient", "familiar", "beginner"}

# A single resume claim may be attacked at most twice before the planner must
# switch dimension / claim.  Mirrors the product's "追问两次" guard.
PROJECT_CLAIM_MAX_FOLLOWUPS = 2
PROJECT_QUESTION_SHARE_TARGET = 0.7

# A project deep-dive question must reference at least this many distinctive
# claim concepts, otherwise it is an unattached 八股 question pretending to be
# a project question (e.g. "解释 Go context.Context" for a Redis/Kafka claim).
PROJECT_QUESTION_BINDING_MIN_TERMS = 2

# Concept terms so generic that they cannot bind a question to a resume claim.
# "deadline" belongs to both "ACK Deadline" (claim) and a generic context
# question, so it must never count toward binding on its own.
_GENERIC_CONCEPT_TERMS = frozenset(
    {
        # English generic infrastructure / interview vocabulary.
        "context", "deadline", "timeout", "cancel", "cancelation", "cancellation",
        "error", "errors", "retry", "retries", "message", "messages", "queue",
        "queues", "cache", "pool", "buffer", "thread", "threads", "lock", "locks",
        "mutex", "channel", "channels", "goroutine", "goroutines", "async",
        "synchronous", "process", "processes", "status", "state", "states",
        "flow", "flows", "delay", "latency", "count", "counts", "system",
        "systems", "service", "services", "server", "servers", "worker",
        "workers", "task", "tasks", "job", "jobs", "event", "events",
        "config", "configuration", "load", "traffic", "request", "requests",
        "response", "responses", "consistency", "availability", "durability",
        "reliability", "fault", "faults", "failure", "failures",
        # Chinese 2-gram function-ish words that co-occur everywhere.
        "实现", "保证", "确保", "支持", "提供", "处理", "负责", "采用", "基于",
        "进行", "通过", "可以", "需要", "使用", "用于", "方式", "机制", "系统",
        "服务", "数据", "性能", "能力", "功能", "过程", "问题", "场景", "情况",
        "时候", "一个", "一次", "之后", "之前", "相关", "核心", "关键", "主要",
    }
)

# Broad technology/product names that appear in many resume claims.  Mentioning
# one of these alone (e.g. "Kafka 分区顺序" or "Redis 缓存") is only the broad
# topic, never evidence that the candidate implemented the claim's mechanism.
_BROAD_TECHNOLOGY_TERMS = frozenset(
    {
        "go", "golang", "java", "jvm", "python", "javascript", "typescript",
        "node", "redis", "kafka", "mysql", "postgres", "postgresql", "mongo",
        "mongodb", "rabbitmq", "rocketmq", "grpc", "gin", "gorm", "spring",
        "react", "fastapi", "django", "docker", "kubernetes", "k8s", "context",
        "goroutine", "channel", "mutex", "thread", "threadpool", "server",
        "gateway", "database", "cache", "queue", "message", "web", "http",
        "rpc", "tcp", "sql", "orm", "oss", "s3", "linux", "nginx", "es",
        "elasticsearch", "zookeeper", "consul", "etcd", "scheduler", "job",
    }
)

# Deterministic failure boundaries used to build claim-specific rubric points.
_PROJECT_DIMENSION_DESCRIPTIONS = {
    "implementation": "实现路径与代码边界（哪些模块/函数/数据结构，如何串联）",
    "selection": "备选方案对比与选择依据（为什么是它而不是其他方案）",
    "failure": "故障窗口与恢复边界（写入成功但后续步骤失败时会发生什么）",
    "tradeoff": "核心取舍（一致性/可用性/成本/复杂度之间的权衡）",
    "data": "数据结构与存储设计（如何组织、落库、变更）",
    "interface": "接口契约与错误边界（上下游如何约定、失败如何暴露）",
    "metric": "指标基线、变量控制与测量方法（如何证明该指标真实成立）",
    "testing": "测试策略与验证手段（单测/压测/故障注入/线上观测）",
}

# Observable language that proves a retrieved chunk / generated question
# actually supports the selected project attack dimension.  Topic and claim
# overlap alone are insufficient: a Redis/Lua implementation note must not
# ground a failure-window question unless it discusses a failure boundary.
_PROJECT_DIMENSION_CUES: dict[str, tuple[str, ...]] = {
    "implementation": ("实现", "流程", "链路", "模块", "函数", "代码", "步骤", "数据流", "写入", "读取", "提交", "调用", "创建", "更新", "释放", "implementation", "workflow", "module", "function", "write", "read", "commit", "call", "update"),
    "selection": ("为什么", "选型", "选择", "替代", "备选", "对比", "方案", "alternative", "instead", "versus", "selection"),
    "failure": ("宕机", "崩溃", "故障", "失败", "异常", "恢复", "重试", "重复", "丢失", "超时", "过期", "补偿", "幂等", "crash", "failure", "recovery", "retry", "duplicate", "loss", "timeout", "idempot"),
    "tradeoff": ("取舍", "权衡", "代价", "成本", "复杂度", "一致性", "可用性", "tradeoff", "trade-off", "cost", "complexity", "consistency", "availability"),
    "data": ("数据", "表", "字段", "索引", "存储", "落库", "结构", "状态", "schema", "table", "column", "index", "storage", "state"),
    "interface": ("接口", "请求", "响应", "错误码", "契约", "上下游", "api", "request", "response", "status code", "contract"),
    "metric": ("指标", "基线", "提升", "降低", "次数", "耗时", "延迟", "吞吐", "测量", "采样", "对比", "压测", "a/b", "metric", "baseline", "latency", "throughput", "benchmark", "measurement"),
    "testing": ("测试", "验证", "用例", "压测", "故障注入", "日志", "监控", "test", "verify", "validation", "benchmark", "fault injection", "log", "monitor"),
}


def matches_project_dimension(text: str, dimension: str) -> bool:
    """Whether text contains an observable cue for one attack dimension."""
    value = str(text or "").lower()
    return any(cue in value for cue in _PROJECT_DIMENSION_CUES.get(str(dimension or ""), ()))

_CLAIM_TYPE_LABELS = {
    "architecture": "架构设计",
    "technology_choice": "技术选型",
    "mechanism": "核心机制",
    "reliability": "可靠性",
    "data_design": "数据设计",
    "interface": "接口设计",
    "metric": "性能指标",
    "testing": "测试与验证",
}

# Planner v2 information-gain factors.  Every factor has an explicit range so
# the deterministic action_value can be audited and replayed term by term.
PLANNER_FINISH_THRESHOLD = 0.05  # stop when the best action_value falls below this
ANCHOR_CONFIDENCE_THRESHOLD = 0.7  # a competency counts as anchored when an anchor
# round scored >=3 with judge confidence above this value
PLANNER_FACTOR_RANGES = {
    "jd_weight": (0.0, 1.0),
    "verification_uncertainty": (0.0, 1.0),
    "expected_information_gain": (0.0, 1.0),
    "resume_risk": (0.0, 1.0),
    "repetition_penalty": (0.0, 1.0),
    "time_cost": (0.0, 1.0),
    "comparability_penalty": (0.0, 1.0),
}


class SessionStatus(StrEnum):
    CREATED = "created"
    PREPARING_QUESTION = "preparing_question"
    AWAITING_ANSWER = "awaiting_answer"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    ABORTED = "aborted"
    FAILED = "failed"


class RoundStatus(StrEnum):
    PREPARING = "preparing"
    AWAITING_ANSWER = "awaiting_answer"
    AWAITING_FOLLOWUP = "awaiting_followup"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    FAILED = "failed"


class Difficulty(StrEnum):
    BEGINNER = "beginner"
    MEDIUM = "medium"
    ADVANCED = "advanced"


class Category(StrEnum):
    INTERVIEW_EXPERIENCE = "interview_experience"
    LEETCODE = "leetcode"
    BAGUWEN = "baguwen"


class RequirementCategory(StrEnum):
    MUST_HAVE = "must_have"
    NICE_TO_HAVE = "nice_to_have"
    RESPONSIBILITY = "responsibility"


class MatchStatus(StrEnum):
    MATCHED = "matched"
    PARTIAL = "partial"
    MISSING = "missing"
    UNKNOWN = "unknown"


class VerificationStatus(StrEnum):
    UNTESTED = "untested"
    VERIFIED = "verified"
    PARTIAL = "partial"
    DISPUTED = "disputed"


class ProjectClaimStatus(StrEnum):
    """Verification state of a single resume project claim.

    ``verified`` means the candidate demonstrated the claimed mechanism/choice
    against a rubric at the required score with project-claim-relevant evidence
    -- never merely "scored well on a related topic".  ``contradiction`` is a
    tracked answer-vs-claim conflict; ``low_confidence`` is an evidence record
    whose judge confidence was too weak to conclude anything.
    """

    UNTESTED = "untested"
    PARTIAL = "partial"
    VERIFIED = "verified"
    DISPUTED = "disputed"
    CONTRADICTION = "contradiction"
    LOW_CONFIDENCE = "low_confidence"


# Claim types a structured resume project claim may carry.  They decide which
# attack dimensions are legal for the claim (see DIMENSIONS_BY_CLAIM_TYPE).
CLAIM_TYPES = (
    "architecture",
    "technology_choice",
    "mechanism",
    "reliability",
    "data_design",
    "interface",
    "metric",
    "testing",
)

# Attack-map target dimensions.  Each dimension drives a distinct probing angle
# on the same resume claim: implementation / selection / failure / tradeoff /
# data / interface / metric / testing.
PROJECT_DIMENSIONS = (
    "implementation",
    "selection",
    "failure",
    "tradeoff",
    "data",
    "interface",
    "metric",
    "testing",
)

# Legal attack dimensions per claim type.  A mechanism claim can be attacked on
# implementation, failure or tradeoff; a metric claim only on metric.
DIMENSIONS_BY_CLAIM_TYPE: dict[str, tuple[str, ...]] = {
    "architecture": ("implementation", "tradeoff", "interface"),
    "technology_choice": ("selection", "tradeoff"),
    "mechanism": ("implementation", "failure", "tradeoff"),
    "reliability": ("failure", "implementation"),
    "data_design": ("data", "tradeoff"),
    "interface": ("interface",),
    "metric": ("metric",),
    "testing": ("testing", "implementation"),
}

# Deterministic risk flags attached to a resume claim.  The extraction engine
# may also suggest flags; the validator unions them with its own deterministic
# detection so the flags are always auditable (see _detect_claim_risk_flags).
CLAIM_RISK_FLAGS = ("vague_metric", "unexplained_choice", "happy_path_only", "keyword_stacking", "missing_validation")

# Project facts the evidence extractor may report.  Each is attributed to a
# project claim (project_id/claim_id) so follow-ups never cross projects.
PROJECT_FACT_KINDS = ("mechanism", "decision", "tradeoff", "failure_mode", "metric_definition")


class PlannerActionKind(StrEnum):
    FOLLOW_UP_CURRENT_CLAIM = "follow_up_current_claim"
    VERIFY_RESUME_CLAIM = "verify_resume_claim"
    VERIFY_JD_REQUIREMENT = "verify_jd_requirement"
    # Project deep-dive: the question targets a concrete resume claim on a
    # specific attack dimension.  The claim decides what to verify; the RAG
    # evidence stays the only source of technical truth.
    VERIFY_PROJECT_CLAIM = "verify_project_claim"
    RESOLVE_CONTRADICTION = "resolve_contradiction"
    SWITCH_TOPIC = "switch_topic"
    ASK_CODING_QUESTION = "ask_coding_question"
    FINISH_INTERVIEW = "finish_interview"


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


SESSION_TRANSITIONS = {
    SessionStatus.CREATED: {SessionStatus.PREPARING_QUESTION, SessionStatus.ABORTED},
    SessionStatus.PREPARING_QUESTION: {SessionStatus.AWAITING_ANSWER, SessionStatus.FAILED, SessionStatus.ABORTED},
    SessionStatus.AWAITING_ANSWER: {SessionStatus.EVALUATING, SessionStatus.ABORTED},
    SessionStatus.EVALUATING: {
        SessionStatus.AWAITING_ANSWER,
        SessionStatus.PREPARING_QUESTION,
        SessionStatus.COMPLETED,
        SessionStatus.FAILED,
        SessionStatus.ABORTED,
    },
    SessionStatus.FAILED: set(),
    SessionStatus.COMPLETED: set(),
    SessionStatus.ABORTED: set(),
}

ROUND_TRANSITIONS = {
    RoundStatus.PREPARING: {RoundStatus.AWAITING_ANSWER, RoundStatus.FAILED},
    RoundStatus.AWAITING_ANSWER: {RoundStatus.EVALUATING, RoundStatus.FAILED},
    RoundStatus.AWAITING_FOLLOWUP: {RoundStatus.EVALUATING, RoundStatus.FAILED},
    RoundStatus.EVALUATING: {RoundStatus.AWAITING_FOLLOWUP, RoundStatus.COMPLETED, RoundStatus.FAILED},
    RoundStatus.COMPLETED: set(),
    RoundStatus.FAILED: set(),
}


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def require_transition(current: str, target: str, transitions: dict) -> None:
    try:
        current_status = next(status for status in transitions if status.value == current)
        target_status = next(status for status in transitions if status.value == target)
    except StopIteration as exc:
        raise DomainError("invalid_status", f"Unknown state transition {current} -> {target}.") from exc
    if target_status not in transitions[current_status]:
        raise DomainError("invalid_transition", f"State cannot change from {current} to {target}.", http_status=409)


def compute_next_difficulty(current: str, score: int, previous_final_score: int | None) -> str:
    """Apply the product's deterministic difficulty policy."""

    levels = [Difficulty.BEGINNER.value, Difficulty.MEDIUM.value, Difficulty.ADVANCED.value]
    if current not in levels:
        raise DomainError("invalid_difficulty", f"Unsupported difficulty: {current}.")
    if score not in range(5):
        raise DomainError("invalid_score", "Score must be an integer from 0 to 4.")
    index = levels.index(current)
    if score <= 1:
        index = max(0, index - 1)
    elif score == 4 and previous_final_score is not None and previous_final_score >= 3:
        index = min(len(levels) - 1, index + 1)
    return levels[index]


VERDICT_SCORE_RANGES = {
    "wrong_or_blank": {0, 1},
    "partial": {2, 3},
    "excellent": {4},
}


@dataclass(frozen=True)
class JudgeResult:
    score: int
    verdict: str
    covered_points: list[str]
    missing_points: list[str]
    factual_errors: list[str]
    needs_followup: bool
    followup_focus: str
    weak_point: str
    feedback: str
    evaluation_summary: str
    confidence: float
    # Project claim-specific judge outputs (see judge.py): they separate
    # technical understanding from claim truthfulness.  ``claim_verification``
    # is the LLM's report only -- the authoritative gate that a claim may not
    # reach ``verified`` without claim-specific answer evidence stays in
    # ``update_project_claim_state``.
    technical_understanding: int = 0
    claim_verification: str = ""
    evidence_from_answer: list[str] = field(default_factory=list)


def validate_judge_result(raw: dict[str, Any], *, followup_count: int, max_followups: int) -> JudgeResult:
    try:
        score = int(raw["score"])
        verdict = str(raw["verdict"])
        confidence = float(raw.get("confidence", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("invalid_judge_output", "Judge output is missing a valid score, verdict, or confidence.") from exc
    if verdict not in VERDICT_SCORE_RANGES or score not in VERDICT_SCORE_RANGES[verdict]:
        raise DomainError("invalid_judge_output", "Judge score and verdict are inconsistent.")
    if not 0 <= confidence <= 1:
        raise DomainError("invalid_judge_output", "Judge confidence must be between 0 and 1.")
    needs_followup = bool(raw.get("needs_followup", False))
    # A weak but concrete attempt can be more diagnostic than a merely partial
    # answer: one focused probe may distinguish a misconception from a wording
    # gap.  Do not spend a follow-up on a blank answer (score 0), an already
    # excellent answer (score 4), or after the configured cap is reached.
    if score in {0, 4} or followup_count >= max_followups:
        needs_followup = False
    followup_focus = str(raw.get("followup_focus", "")).strip() if needs_followup else ""
    if needs_followup and not followup_focus:
        raise DomainError("invalid_judge_output", "An answer that needs follow-up must include followup_focus.")

    def string_list(name: str) -> list[str]:
        value = raw.get(name, [])
        if not isinstance(value, list):
            raise DomainError("invalid_judge_output", f"Judge field {name} must be a list.")
        return [str(item).strip() for item in value if str(item).strip()]

    return JudgeResult(
        score=score,
        verdict=verdict,
        covered_points=string_list("covered_points"),
        missing_points=string_list("missing_points"),
        factual_errors=string_list("factual_errors"),
        needs_followup=needs_followup,
        followup_focus=followup_focus,
        weak_point=str(raw.get("weak_point", "")).strip(),
        feedback=str(raw.get("feedback", "")).strip(),
        evaluation_summary=str(raw.get("evaluation_summary", "")).strip(),
        confidence=confidence,
        technical_understanding=_clamped_int(raw.get("technical_understanding"), 0, 4, default=0),
        claim_verification=_validated_claim_verification(raw.get("claim_verification")),
        evidence_from_answer=_tolerant_string_list(raw.get("evidence_from_answer")),
    )


def _clamped_int(value: Any, minimum: int, maximum: int, *, default: int) -> int:
    try:
        return max(minimum, min(maximum, int(value)))
    except (TypeError, ValueError):
        return default


def _validated_claim_verification(value: Any) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {"verified", "partial", "unverified", "contradiction"}:
        return candidate
    return ""


def _tolerant_string_list(value: Any) -> list[str]:
    """Optional string list that tolerates null/absent without failing a judge."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


EVIDENCE_KINDS = ("technical_claim", "decision", "mechanism", "tradeoff", "example", "contradiction")


@dataclass(frozen=True)
class RubricScore:
    """Stage-2 output of the evidence-level judge."""

    score: int
    matched_anchor: int
    verdict: str
    matched_indicators: list[str]
    missing_indicators: list[str]
    evidence_span_ids: list[str]
    confidence: float
    needs_followup: bool
    followup_focus: str
    weak_point: str
    feedback: str
    evaluation_summary: str
    factual_errors: list[str]
    # Project claim-specific scoring.  ``technical_understanding`` (0..4) is
    # whether the candidate understands the technology; ``claim_verification``
    # is the LLM report of whether the answer proved the resume claim;
    # ``evidence_from_answer`` are exact quotes of the candidate's own
    # implementation detail.  Generic-principle answers may earn technical
    # credit but must never report ``claim_verification == verified``.
    technical_understanding: int = 0
    claim_verification: str = ""
    evidence_from_answer: list[str] = field(default_factory=list)
    claim_missing_points: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class EvidenceExtraction:
    """Stage-1 output: evidence extracted from the candidate answer."""

    answer_spans: list[dict[str, Any]]
    technical_claims: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    mechanisms: list[dict[str, Any]]
    tradeoffs: list[dict[str, Any]]
    examples: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    uncertainty_phrases: list[str]
    matched_indicators: list[dict[str, Any]]
    missing_indicators: list[dict[str, Any]]
    answer_state: dict[str, Any]


@dataclass(frozen=True)
class EvidenceEvaluation:
    """Immutable record of all three judge stages for a candidate answer."""

    extraction: dict[str, Any]
    scorer: dict[str, Any]
    validator: dict[str, Any]
    low_confidence: bool


def _exact_span(raw: Any, answer: str, *, limit: int = 500) -> str:
    text = str(raw or "").strip()[:limit]
    return text if text and text in answer else ""


def validate_evidence_extraction(
    raw: dict[str, Any],
    answer: str,
    known_claims: Iterable[str] = (),
    known_project_claims: dict[str, str] | None = None,
) -> EvidenceExtraction:
    """Validate stage-1 extraction. Every span must be an exact answer quote."""
    if not isinstance(raw, dict):
        raise DomainError("invalid_evidence_extraction", "Evidence extraction must be a JSON object.")

    def spans() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in raw.get("answer_spans", [])[:60]:
            if not isinstance(item, dict):
                continue
            span_id = str(item.get("span_id") or "").strip()
            text = _exact_span(item.get("text"), answer)
            if not span_id or not text:
                continue
            result.append({"span_id": span_id, "text": text, "start": answer.find(text), "end": answer.find(text) + len(text)})
        return result

    extracted_spans = spans()

    def claims(name: str) -> list[dict[str, Any]]:
        result = []
        values = raw.get(name, [])
        if not isinstance(values, list):
            return result
        for item in values[:40]:
            if not isinstance(item, dict):
                continue
            claim_id = str(item.get("claim_id") or "").strip()
            text = str(item.get("text") or "").strip()[:500]
            if not claim_id or not text:
                continue
            span_ids = [str(s) for s in item.get("span_ids", []) if str(s) in {s["span_id"] for s in extracted_spans}]
            if not span_ids:
                continue
            topic_ids = [str(t) for t in item.get("topic_ids", []) if str(t) in topic_catalog()]
            result.append({"claim_id": claim_id, "text": text, "span_ids": span_ids, "topic_ids": topic_ids})
        return result

    def indicators(name: str) -> list[dict[str, Any]]:
        result = []
        values = raw.get(name, [])
        if not isinstance(values, list):
            return result
        for item in values[:40]:
            if not isinstance(item, dict):
                continue
            indicator = str(item.get("indicator") or "").strip()[:300]
            if not indicator:
                continue
            try:
                level = max(0, min(4, int(item.get("anchor_level", 0))))
            except (TypeError, ValueError):
                level = 0
            span_ids = [str(s) for s in item.get("span_ids", []) if str(s) in {s["span_id"] for s in extracted_spans}] if name == "matched_indicators" else []
            result.append({"indicator": indicator, "anchor_level": level, "span_ids": span_ids})
        return result

    matched = indicators("matched_indicators")
    missing = [item for item in indicators("missing_indicators") if item["anchor_level"] > 0]
    contradictions = []
    for item in claims("contradictions"):
        conflicts_with = str(item.get("conflicts_with") or "").strip()[:500]
        if conflicts_with and _normalized_phrase(conflicts_with) not in _normalized_phrase("\n".join(str(c) for c in known_claims)):
            continue
        contradictions.append({**item, "conflicts_with": conflicts_with})
    uncertainty_phrases = list(dict.fromkeys(str(p).strip()[:200] for p in raw.get("uncertainty_phrases", []) if str(p).strip()))[:20]
    return EvidenceExtraction(
        answer_spans=extracted_spans,
        technical_claims=claims("technical_claims"),
        decisions=claims("decisions"),
        mechanisms=claims("mechanisms"),
        tradeoffs=claims("tradeoffs"),
        examples=claims("examples"),
        contradictions=contradictions,
        uncertainty_phrases=uncertainty_phrases,
        matched_indicators=matched,
        missing_indicators=missing,
        answer_state=validate_answer_state(raw, answer, known_claims, known_project_claims=known_project_claims),
    )


def validate_rubric_score(raw: dict[str, Any], extraction: EvidenceExtraction, *, followup_count: int, max_followups: int) -> RubricScore:
    """Validate stage-2 scorer output against the extracted evidence."""
    if not isinstance(raw, dict):
        raise DomainError("invalid_rubric_score", "Rubric score must be a JSON object.")
    try:
        score = int(raw["score"])
        matched_anchor = int(raw.get("matched_anchor", score))
        confidence = float(raw.get("confidence", 0))
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("invalid_rubric_score", "Rubric score is missing a valid score, matched_anchor, or confidence.") from exc
    verdict = str(raw.get("verdict") or "")
    if verdict not in VERDICT_SCORE_RANGES or score not in VERDICT_SCORE_RANGES[verdict]:
        raise DomainError("invalid_rubric_score", "Rubric score and verdict are inconsistent.")
    if matched_anchor != score:
        raise DomainError("invalid_rubric_score", "matched_anchor must equal the score.")
    if not 0 <= confidence <= 1:
        raise DomainError("invalid_rubric_score", "Rubric confidence must be between 0 and 1.")
    valid_span_ids = {item["span_id"] for item in extraction.answer_spans}
    evidence_span_ids = [str(item) for item in raw.get("evidence_span_ids", []) if str(item) in valid_span_ids]
    if score >= 3 and not evidence_span_ids:
        raise DomainError("invalid_rubric_score", "A high score requires at least one real evidence span.")
    needs_followup = bool(raw.get("needs_followup", False))
    if score in {0, 4} or followup_count >= max_followups:
        needs_followup = False
    followup_focus = str(raw.get("followup_focus", "")).strip() if needs_followup else ""
    if needs_followup and not followup_focus:
        raise DomainError("invalid_rubric_score", "An answer that needs follow-up must include followup_focus.")

    def string_list(name: str) -> list[str]:
        value = raw.get(name, [])
        if not isinstance(value, list):
            raise DomainError("invalid_rubric_score", f"Rubric field {name} must be a list.")
        return [str(item).strip() for item in value if str(item).strip()]

    evidence_from_answer = [
        quote
        for quote in _tolerant_string_list(raw.get("evidence_from_answer"))
        if any(quote in str(span.get("text") or "") for span in extraction.answer_spans)
    ]
    return RubricScore(
        score=score,
        matched_anchor=matched_anchor,
        verdict=verdict,
        matched_indicators=string_list("matched_indicators"),
        missing_indicators=string_list("missing_indicators"),
        evidence_span_ids=evidence_span_ids,
        confidence=confidence,
        needs_followup=needs_followup,
        followup_focus=followup_focus,
        weak_point=str(raw.get("weak_point", "")).strip(),
        feedback=str(raw.get("feedback", "")).strip(),
        evaluation_summary=str(raw.get("evaluation_summary", "")).strip(),
        factual_errors=string_list("factual_errors"),
        technical_understanding=_clamped_int(raw.get("technical_understanding"), 0, 4, default=0),
        claim_verification=_validated_claim_verification(raw.get("claim_verification")),
        # Claim evidence must be an exact quote already extracted from the
        # candidate answer; model-authored paraphrases are not evidence.
        evidence_from_answer=list(dict.fromkeys(evidence_from_answer)),
        claim_missing_points=_tolerant_string_list(raw.get("claim_missing_points")),
    )


def consistency_issues(
    scorer: RubricScore,
    extraction: EvidenceExtraction,
    *,
    code_result: dict[str, Any] | None,
) -> list[str]:
    """Stage-3 deterministic consistency checks.

    Returns a list of issues. The caller retries the scorer once on failure and
    must never silently accept an inconsistent result; a result that still fails
    becomes low-confidence (see EvidenceEvaluation.low_confidence).
    """
    issues: list[str] = []
    if scorer.matched_anchor != scorer.score:
        issues.append("score does not match the reported score anchor")
    if scorer.score >= 3 and not scorer.evidence_span_ids:
        issues.append("high score lacks supporting answer evidence")
    if not scorer.evidence_span_ids and scorer.score >= 2:
        issues.append("score 2+ must cite at least one answer span")
    valid_span_ids = {item["span_id"] for item in extraction.answer_spans}
    if any(span_id not in valid_span_ids for span_id in scorer.evidence_span_ids):
        issues.append("evidence_span_ids reference spans that do not exist")
    if not 0 <= scorer.confidence <= 1:
        issues.append("confidence must be within 0..1")
    if scorer.score >= 3 and scorer.confidence < 0.4:
        issues.append("high score with low judge confidence")
    matched_texts = {str(item.get("indicator")) for item in extraction.matched_indicators}
    for indicator in scorer.matched_indicators:
        if indicator and indicator not in matched_texts:
            issues.append("scorer cites an indicator not extracted from the answer")
    # Same fact double-counted: a span may not justify the score twice.
    if len(scorer.evidence_span_ids) != len(set(scorer.evidence_span_ids)):
        issues.append("the same evidence span is counted more than once")
    if scorer.claim_verification == "verified" and not scorer.evidence_from_answer:
        issues.append("claim verified without any claim-specific answer evidence")
    if scorer.claim_verification == "verified" and scorer.technical_understanding < 2:
        issues.append("claim verified but technical understanding is low")
    if scorer.claim_verification and not scorer.claim_verification in {"verified", "partial", "unverified", "contradiction"}:
        issues.append("claim_verification has an unsupported value")
    if code_result is not None:
        status = str(code_result.get("status") or "")
        passed = int(code_result.get("passed_count") or 0)
        total = int(code_result.get("total_count") or 0)
        if status == "completed" and total and passed == total and scorer.score <= 1:
            issues.append("all code tests passed but the answer scores 0 or 1")
        if status in {"compile_error", "runtime_error", "timeout"} and scorer.score >= 4:
            issues.append("code did not pass but the answer scores 4")
        if status == "completed" and total and passed < total and scorer.score == 4:
            issues.append("not all code tests passed but the answer scores 4")
    return issues


def evaluation_to_judge_result(evaluation: EvidenceEvaluation) -> JudgeResult:
    """Project the stored 3-stage evaluation onto the legacy JudgeResult shape."""
    scorer = evaluation.scorer
    # Claim-specific gaps drive project follow-ups; generic competency
    # indicators are only the fallback for foundation questions.
    missing = list(
        dict.fromkeys(
            [
                *(scorer.get("claim_missing_points") or []),
                *(scorer.get("missing_indicators") or []),
            ]
        )
    )
    needs_followup = bool(scorer.get("needs_followup", False))
    return JudgeResult(
        score=int(scorer["score"]),
        verdict=str(scorer["verdict"]),
        covered_points=list(scorer.get("matched_indicators") or []),
        missing_points=missing,
        factual_errors=list(scorer.get("factual_errors") or []),
        needs_followup=needs_followup,
        followup_focus=str(scorer.get("followup_focus") or "") if needs_followup else "",
        weak_point=str(scorer.get("weak_point") or ""),
        feedback=str(scorer.get("feedback") or ""),
        evaluation_summary=str(scorer.get("evaluation_summary") or ""),
        confidence=float(scorer.get("confidence") or 0),
        technical_understanding=_clamped_int(scorer.get("technical_understanding"), 0, 4, default=0),
        claim_verification=_validated_claim_verification(scorer.get("claim_verification")),
        evidence_from_answer=_tolerant_string_list(scorer.get("evidence_from_answer")),
    )


@dataclass(frozen=True)
class TopicDefinition:
    id: str
    name: str
    weight: float
    difficulties: tuple[str, ...]
    question_types: tuple[str, ...]
    categories: tuple[str, ...]
    minimum_coverage: int
    supports_code: bool
    retest_after: int


def _topic(
    topic_id: str,
    name: str,
    weight: float,
    categories: tuple[str, ...],
    question_types: tuple[str, ...] = ("theory", "scenario"),
    *,
    minimum: int = 1,
    code: bool = False,
    difficulties: tuple[str, ...] = ("beginner", "medium", "advanced"),
    retest_after: int = 3,
) -> TopicDefinition:
    return TopicDefinition(topic_id, name, weight, difficulties, question_types, categories, minimum, code, retest_after)


ROLE_CAPABILITY_TREES: dict[str, tuple[TopicDefinition, ...]] = {
    "go_backend": (
        _topic("go.runtime", "Go 运行时与并发", 1.4, ("baguwen", "interview_experience")),
        _topic("database.mysql", "MySQL 与事务", 1.2, ("baguwen", "interview_experience")),
        _topic("backend.distributed", "分布式系统", 1.1, ("interview_experience", "baguwen")),
        _topic("algorithm.core", "算法与数据结构", 1.0, ("leetcode",), ("coding",), code=True),
    ),
    "java_backend": (
        _topic("java.jvm", "JVM 与并发", 1.4, ("baguwen", "interview_experience")),
        _topic("java.spring", "Spring 与服务治理", 1.2, ("interview_experience", "baguwen")),
        _topic("database.mysql", "MySQL 与事务", 1.1, ("baguwen", "interview_experience")),
        _topic("algorithm.core", "算法与数据结构", 1.0, ("leetcode",), ("coding",), code=True),
    ),
    "python_backend": (
        _topic("python.runtime", "Python 运行时与并发", 1.3, ("baguwen", "interview_experience")),
        _topic("python.web", "Web 框架与异步服务", 1.2, ("interview_experience", "baguwen")),
        _topic("backend.distributed", "分布式系统", 1.0, ("interview_experience", "baguwen")),
        _topic("algorithm.core", "算法与数据结构", 1.0, ("leetcode",), ("coding",), code=True),
    ),
    "frontend": (
        _topic("frontend.javascript", "JavaScript 与浏览器", 1.4, ("baguwen", "interview_experience")),
        _topic("frontend.react", "React 工程实践", 1.2, ("interview_experience", "baguwen")),
        _topic("frontend.performance", "性能与可访问性", 1.1, ("interview_experience", "baguwen")),
        _topic("algorithm.core", "算法与数据结构", 0.9, ("leetcode",), ("coding",), code=True),
    ),
    "ml_engineer": (
        _topic("ml.fundamentals", "机器学习基础", 1.4, ("baguwen", "interview_experience")),
        _topic("ml.system", "训练与推理系统", 1.2, ("interview_experience", "baguwen")),
        _topic("ml.evaluation", "数据与评测", 1.1, ("interview_experience", "baguwen")),
        _topic("algorithm.core", "算法与数据结构", 1.0, ("leetcode",), ("coding",), code=True),
    ),
    "ai_backend": (
        _topic("ai.rag", "RAG 检索与有依据生成", 1.4, ("interview_experience", "baguwen")),
        _topic("ai.agent", "Agent 工具调用与工作流", 1.2, ("interview_experience", "baguwen")),
        _topic("ai.evaluation", "大模型应用评测", 1.1, ("baguwen", "interview_experience")),
        _topic("algorithm.core", "算法与数据结构", 1.0, ("leetcode",), ("coding",), code=True),
    ),
    "sdet": (
        _topic("testing.strategy", "测试策略与质量工程", 1.4, ("interview_experience", "baguwen")),
        _topic("testing.automation", "自动化测试", 1.2, ("interview_experience", "baguwen")),
        _topic("testing.performance", "性能与稳定性", 1.0, ("interview_experience", "baguwen")),
        _topic("algorithm.core", "算法与数据结构", 0.8, ("leetcode",), ("coding",), code=True),
    ),
    "cs_general": (
        _topic("os.core", "操作系统", 1.1, ("baguwen", "interview_experience")),
        _topic("network.core", "计算机网络", 1.1, ("baguwen", "interview_experience")),
        _topic("database.core", "数据库", 1.1, ("baguwen", "interview_experience")),
        _topic("algorithm.core", "算法与数据结构", 1.1, ("leetcode",), ("coding",), code=True),
    ),
}


def topic_catalog() -> dict[str, str]:
    """Flatten ROLE_CAPABILITY_TREES into {topic_id: topic_name} for the extraction prompt."""
    return {topic.id: topic.name for tree in ROLE_CAPABILITY_TREES.values() for topic in tree}


def _project_id(name: str, role: str) -> str:
    """Stable project identity derived only from resume content.

    The id depends only on the normalized project name + role, so the same
    project re-extracted (even by a different model run) maps to the same id.
    It is never generated by the extraction model.
    """
    digest = hashlib.sha256(f"{str(name or '').strip()}\n{str(role or '').strip()}".encode()).hexdigest()[:14]
    return f"proj-{digest}"


def _claim_id(project_id: str, text: str) -> str:
    """Stable claim identity derived only from the project + claim text."""
    digest = hashlib.sha256(f"{project_id}\x00{_normalized_phrase(text)}".encode()).hexdigest()[:16]
    return f"clm-{digest}"


def _strip_for_span(value: str) -> str:
    """Whitespace/punctuation-insensitive form used for tolerant span matching."""
    return re.sub(r"\s+|[\W_]+", "", value)


_VAGUE_METRIC_PATTERN = re.compile(r"(提升|优化|改善|加快|降低|提高|增强).{0,10}(性能|效率|吞吐|延迟|速度|稳定性|可用性)|高可用|防止.{0,4}重复|大幅|显著|明显|很大|极大|非常")
_UNEXPLAINED_CHOICE_PATTERN = re.compile(r"(采用|选用|引入|选择了)")
_REASON_TERMS = ("因为", "考虑到", "相比", "为了", "权衡", "瓶颈", "成本", "替代", "对比", "限制", "约束", "要求", "由于", "以避免", "而不是")
_FAILURE_TERMS = ("失败", "异常", "崩溃", "并发", "超时", "恢复", "回滚", "降级", "容错", "重试", "熔断", "缓存失效", "丢失", "一致", "抖动", "抖动", "不可用", "宕机", "挂掉", "卡死", "死锁", "热点")
_NORMAL_PATH_TERMS = ("实现", "完成", "上线", "支持", "提供", "负责", "开发", "维护")
_MECHANISM_VERBS = ("实现", "处理", "通过", "基于", "调用", "分发", "写入", "读取", "调度", "缓存", "聚合", "转换", "解析", "路由", "同步", "异步")
_METRIC_UNITS_PATTERN = re.compile(r"\d+(\.\d+)?\s*(%|毫秒|ms|秒|s|tps|qps|rps|倍|万|亿|分钟)")
_BASELINE_TERMS = ("提升前", "基线", "对比", "从", "降低到", "提升到", "增长", "原", "before", "baseline", "原先", "过去", "之前")


def _detect_claim_risk_flags(text: str, skills: list[str]) -> list[str]:
    """Deterministic risk-flag detection over a claim's text.

    The extraction model may also suggest flags; ``validate_resume_extraction``
    unions them with these so the flags are reproducible and auditable.
    """
    flags: list[str] = []
    has_metric_unit = bool(_METRIC_UNITS_PATTERN.search(text))
    if _VAGUE_METRIC_PATTERN.search(text) and not has_metric_unit:
        flags.append("vague_metric")
    if _UNEXPLAINED_CHOICE_PATTERN.search(text) and not any(term in text for term in _REASON_TERMS):
        flags.append("unexplained_choice")
    if any(term in text for term in _NORMAL_PATH_TERMS) and not any(term in text for term in _FAILURE_TERMS):
        flags.append("happy_path_only")
    mechanism_hits = sum(term in text for term in _MECHANISM_VERBS)
    if len([skill for skill in (skills or []) if str(skill).strip()]) >= 3 and mechanism_hits == 0:
        flags.append("keyword_stacking")
    if has_metric_unit and not any(term in text for term in _BASELINE_TERMS):
        flags.append("missing_validation")
    return flags


def _locate_evidence_span(text: str, source_text: str, *, limit: int = 600) -> str:
    """Return the contiguous resume substring that backs ``text``.

    Exact matches win immediately.  When the model drifts on whitespace or
    punctuation, the span is located by matching the whitespace/punctuation-
    insensitive form and returning the exact source slice -- the returned span
    is always contiguous text from the resume.  Returns "" when nothing matches,
    so a fabricated evidence_span is never accepted.
    """
    raw = str(text or "").strip()[:limit]
    source = str(source_text or "")
    if not raw or not source:
        return ""
    if raw in source:
        return raw
    needle = _strip_for_span(raw)
    if not needle:
        return ""
    stripped_indices = [index for index, char in enumerate(source) if _strip_for_span(char)]
    needle_chars = list(needle)
    if len(needle_chars) > len(stripped_indices):
        return ""
    for start in range(len(stripped_indices) - len(needle_chars) + 1):
        if all(_strip_for_span(source[stripped_indices[start + offset]]) == needle_chars[offset] for offset in range(len(needle_chars))):
            return source[stripped_indices[start] : stripped_indices[start + len(needle_chars) - 1] + 1]
    return ""


def validate_resume_extraction(raw: dict[str, Any], source_text: str | None = None) -> dict[str, Any]:
    """Deterministically clamp/validate the v2 resume extraction into the stored shape.

    Projects now carry stable ``project_id`` / ``claim_id`` (derived only from
    resume content), a contiguous ``evidence_span`` for every claim (never
    model-invented), typed claims and auditable risk flags.  Old v1 extractions
    are rejected here and must be re-extracted (see EXTRACTION_VERSION).

    Mirrors validate_judge_result: pure, strict enough to reject unusable output,
    tolerant enough to keep a mostly-good extraction. Raises DomainError on output
    that contains no usable candidate information at all.
    """
    if not isinstance(raw, dict):
        raise DomainError("invalid_extraction", "Resume extraction must be a JSON object.")

    source = str(source_text or "")
    catalog = topic_catalog()
    result: dict[str, Any] = {}

    role = raw.get("target_role")
    if isinstance(role, str) and role in ROLE_CAPABILITY_TREES:
        result["target_role"] = role

    level = raw.get("target_level")
    if isinstance(level, str) and level in {"junior", "mid", "senior", "staff"}:
        result["target_level"] = level

    def _string_list(name: str, limit: int = 50) -> list[str]:
        value = raw.get(name, [])
        if not isinstance(value, list):
            return []
        items = [str(item).strip() for item in value if str(item).strip()]
        return list(dict.fromkeys(items))[:limit]

    stack = list(
        dict.fromkeys(
            [
                *_string_list("technology_stack"),
                *_technology_stack_from_text(source),
            ]
        )
    )[:50]
    if stack:
        result["technology_stack"] = stack

    claimed: list[dict[str, Any]] = []
    for item in raw.get("claimed_skills", []):
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill") or "").strip()
        if not skill or len(skill) > 128:
            continue
        claimed_level = str(item.get("claimed_level") or "familiar").strip().lower()
        if claimed_level not in CLAIMED_LEVELS:
            claimed_level = "familiar"
        topics = [str(t) for t in item.get("topics", []) if str(t) in catalog]
        topics = list(dict.fromkeys([*topics, *sorted(_topics_for_phrase(skill))]))
        claimed.append({"skill": skill, "claimed_level": claimed_level, "topics": topics})
    claimed_names = {_normalized_phrase(item["skill"]) for item in claimed}
    for technology in stack:
        topics = sorted(_topics_for_phrase(technology))
        normalized = _normalized_phrase(technology)
        if not topics or normalized in claimed_names:
            continue
        claimed.append({"skill": technology, "claimed_level": "familiar", "topics": topics})
        claimed_names.add(normalized)
    if claimed:
        result["claimed_skills"] = claimed

    projects: list[dict[str, Any]] = []
    for item in raw.get("projects", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or len(name) > 255:
            continue
        role = str(item.get("role") or "").strip()[:128]
        summary = str(item.get("summary") or "").strip()[:2000]
        if len(summary) < 12:
            # A project summary that is only a stack list (or empty) cannot
            # anchor project deep-dives: business goal + candidate role are the
            # minimum a probe can reference.
            continue
        project_skills = _string_list_from(item, "skills")
        project_id = _project_id(name, role)
        claims: list[dict[str, Any]] = []
        for claim in item.get("claims", []):
            if not isinstance(claim, dict):
                continue
            text = str(claim.get("text") or "").strip()[:500]
            if not text:
                continue
            evidence_span = _locate_evidence_span(str(claim.get("evidence_span") or ""), source)
            if not evidence_span:
                continue
            claim_type = str(claim.get("claim_type") or "mechanism").strip().lower()
            if claim_type not in CLAIM_TYPES:
                claim_type = "mechanism"
            claim_skills = _string_list_from(claim, "skills")
            topics = [str(t) for t in claim.get("topic_ids", []) if str(t) in catalog]
            deterministic_topics = {
                topic_id
                for phrase in [text, *claim_skills, *project_skills]
                for topic_id in _topics_for_phrase(phrase)
            }
            topics = list(dict.fromkeys([*topics, *sorted(deterministic_topics)]))
            claim_id = _claim_id(project_id, text)
            risk_flags = list(
                dict.fromkeys(
                    [
                        flag
                        for flag in [*_detect_claim_risk_flags(text, [*claim_skills, *project_skills]), *(str(f) for f in claim.get("risk_flags", []) if str(f).strip().lower() in CLAIM_RISK_FLAGS)]
                    ]
                )
            )
            claims.append(
                {
                    "claim_id": claim_id,
                    "claim_type": claim_type,
                    "text": text,
                    "evidence_span": evidence_span,
                    "topic_ids": topics,
                    "skills": claim_skills,
                    "risk_flags": risk_flags,
                }
            )
        projects.append(
            {
                "project_id": project_id,
                "name": name,
                "role": role,
                "summary": summary,
                "skills": project_skills,
                "claims": claims,
            }
        )
    if projects:
        result["projects"] = projects[:30]

    years = raw.get("years_of_experience")
    if isinstance(years, (int, float)) and not isinstance(years, bool):
        result["years_of_experience"] = max(0.0, min(float(years), 60.0))

    summary = str(raw.get("summary") or "").strip()[:2000]
    if summary:
        result["summary"] = summary

    if not any(key in result for key in ("claimed_skills", "projects", "technology_stack")):
        raise DomainError(
            "invalid_extraction",
            "The resume extraction did not contain any usable candidate information.",
        )
    return result


def _string_list_from(item: dict[str, Any], name: str, limit: int = 50) -> list[str]:
    value = item.get(name, [])
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(x).strip() for x in value if str(x).strip()))[:limit]


@dataclass(frozen=True)
class JDRequirement:
    requirement_id: str
    text: str
    category: str
    skills: list[str]
    topic_ids: list[str]
    expected_level: str
    weight: float
    evidence_span: str
    extraction_confidence: float
    unmapped: bool


@dataclass(frozen=True)
class RequirementMatch:
    requirement_id: str
    resume_evidence: list[dict[str, Any]]
    claimed_level: str | None
    match_status: str
    risk_level: str
    verification_status: str
    match_basis: list[str]


@dataclass(frozen=True)
class CandidateState:
    newly_claimed_facts: list[dict[str, Any]]
    verified_facts: list[dict[str, Any]]
    disputed_facts: list[dict[str, Any]]
    contradictions: list[dict[str, Any]]
    weak_points: list[str]
    strong_points: list[str]
    unanswered_hypotheses: list[dict[str, Any]]
    covered_requirement_ids: list[str]
    next_action_reason: str
    # Frozen project attack map (built once from the resume/JD/competency
    # snapshots) plus the mutable per-target verification state.  The map is
    # never regenerated mid-session; only statuses/attempts mutate.
    project_attack_map: list[dict[str, Any]] = field(default_factory=list)
    project_facts: list[dict[str, Any]] = field(default_factory=list)
    project_claim_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InterviewPlanItem:
    requirement_id: str
    topic_id: str
    priority: float
    objective: str
    preferred_question_type: str
    target_difficulty: str
    verification_strategy: str
    status: str
    attempt_count: int
    competency_id: str = ""
    must_have: bool = False


@dataclass(frozen=True)
class PlannerAction:
    selected_action: str
    target_requirement_id: str | None
    target_topic: str | None
    reason: str
    supporting_state: dict[str, Any]
    planner_version: str = PLANNER_VERSION
    followup_focus: str = ""
    target_contradiction_id: str = ""
    target_difficulty: str = Difficulty.MEDIUM.value
    preferred_question_type: str = "scenario"
    decision_audit: dict[str, Any] = field(default_factory=dict)
    # Competency + anchor metadata for comparability.  question_kind is one of
    # anchor / adaptive / coding: the first question on a must-have competency
    # is an "anchor" (a stable baseline), later questions are "adaptive".
    question_kind: str = "adaptive"
    competency_id: str = ""
    anchor_group_id: str = ""
    expected_evidence: dict[str, Any] = field(default_factory=dict)
    # Deterministic planner v2 factor breakdown (see PLANNER_FACTOR_RANGES).
    action_factors: dict[str, Any] = field(default_factory=dict)
    # Project deep-dive targeting.  verify_project_claim and project follow-up
    # actions carry the resume claim being attacked, the attack dimension and
    # the current follow-up depth (capped at PROJECT_CLAIM_MAX_FOLLOWUPS).
    target_project_id: str = ""
    target_claim_id: str = ""
    project_dimension: str = ""
    project_followup_depth: int = 0


_REQUIREMENT_BASE_WEIGHTS = {
    RequirementCategory.MUST_HAVE.value: 3.0,
    RequirementCategory.RESPONSIBILITY.value: 2.0,
    RequirementCategory.NICE_TO_HAVE.value: 1.0,
}

_EXPECTED_LEVELS = {
    "beginner",
    "medium",
    "advanced",
    "junior",
    "mid",
    "senior",
    "staff",
    "unspecified",
}

_TECHNOLOGY_TOPIC_ALIASES: dict[str, tuple[str, ...]] = {
    "go": ("go.runtime",),
    "golang": ("go.runtime",),
    "goroutine": ("go.runtime",),
    "channel": ("go.runtime",),
    "gin": ("go.runtime",),
    "gorm": ("go.runtime", "database.core"),
    "grpc": ("backend.distributed",),
    "java": ("java.jvm", "java.spring"),
    "jvm": ("java.jvm",),
    "spring": ("java.spring",),
    "python": ("python.runtime", "python.web"),
    "quart": ("python.web",),
    "fastapi": ("python.web",),
    "django": ("python.web",),
    "javascript": ("frontend.javascript",),
    "typescript": ("frontend.javascript",),
    "react": ("frontend.react",),
    "mysql": ("database.mysql", "database.core"),
    "postgresql": ("database.core",),
    "postgres": ("database.core",),
    "redis": ("backend.distributed",),
    "kafka": ("backend.distributed",),
    "rabbitmq": ("backend.distributed",),
    "rocketmq": ("backend.distributed",),
    "tcp": ("network.core",),
    "websocket": ("network.core",),
    "restful": ("network.core",),
    "消息队列": ("backend.distributed",),
    "微服务": ("backend.distributed",),
    "分布式": ("backend.distributed",),
    "rag": ("ai.rag",),
    "retrieval": ("ai.rag",),
    "embedding": ("ai.rag",),
    "rerank": ("ai.rag",),
    "检索": ("ai.rag",),
    "agent": ("ai.agent",),
    "workflow": ("ai.agent",),
    "tool calling": ("ai.agent",),
    "工具调用": ("ai.agent",),
    "评测": ("ai.evaluation", "ml.evaluation"),
    "evaluation": ("ai.evaluation", "ml.evaluation"),
    "machine learning": ("ml.fundamentals",),
    "机器学习": ("ml.fundamentals",),
    "自动化测试": ("testing.automation",),
    "性能测试": ("testing.performance",),
    "算法": ("algorithm.core",),
}

_RESUME_TECHNOLOGY_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Go", ("go", "golang")),
    ("Java", ("java",)),
    ("Python", ("python",)),
    ("JavaScript", ("javascript",)),
    ("TypeScript", ("typescript",)),
    ("React", ("react",)),
    ("Vue", ("vue", "vue.js")),
    ("Spring Boot", ("spring boot",)),
    ("Spring", ("spring",)),
    ("Gin", ("gin",)),
    ("GORM", ("gorm",)),
    ("gRPC", ("grpc",)),
    ("FastAPI", ("fastapi",)),
    ("Django", ("django",)),
    ("Flask", ("flask",)),
    ("Quart", ("quart",)),
    ("MySQL", ("mysql",)),
    ("PostgreSQL", ("postgresql", "postgres")),
    ("MongoDB", ("mongodb",)),
    ("Redis", ("redis",)),
    ("Kafka", ("kafka",)),
    ("RabbitMQ", ("rabbitmq",)),
    ("RocketMQ", ("rocketmq",)),
    ("Elasticsearch", ("elasticsearch",)),
    ("MinIO", ("minio",)),
    ("Docker", ("docker",)),
    ("Kubernetes", ("kubernetes", "k8s")),
    ("Linux", ("linux",)),
    ("TCP", ("tcp",)),
    ("WebSocket", ("websocket",)),
    ("SSE", ("sse",)),
    ("RAGFlow", ("ragflow",)),
    ("RAG", ("rag",)),
    ("LangChain", ("langchain",)),
    ("LlamaIndex", ("llamaindex",)),
    ("PyTorch", ("pytorch",)),
    ("TensorFlow", ("tensorflow",)),
)


def _technology_stack_from_text(value: Any) -> list[str]:
    """Recover explicitly mentioned technologies when model extraction is sparse."""
    text = str(value or "").lower()
    technologies: list[str] = []
    for canonical, aliases in _RESUME_TECHNOLOGY_ALIASES:
        for alias in aliases:
            pattern = rf"(?<![a-z0-9]){re.escape(alias.lower())}(?![a-z0-9])"
            if re.search(pattern, text):
                technologies.append(canonical)
                break
    return technologies


def _normalized_phrase(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff+#.]+", "", str(value).strip().lower())


_ENGLISH_CONCEPT_TOKEN = re.compile(r"[a-z0-9+#]+")
_CHINESE_CHAR = re.compile(r"[\u4e00-\u9fff]")


def concept_terms(text: str) -> set[str]:
    """Deterministic Chinese/English technical concept tokens of ``text``.

    English tokens are lower-cased ``[a-z0-9+#]+`` runs (camelCase and
    acronyms collapse to their word-level pieces); Chinese text is split into
    sliding 2-grams so mechanisms like "\u53ef\u9760\u6295\u9012" / "\u79df\u7ea6" survive while
    generic bigrams are filtered by :data:`_GENERIC_CONCEPT_TERMS` at binding
    time.  The same normalizer is used for claim evidence relevance and for the
    project-question binding gate, so the gate never depends on an LLM's
    self-report of relevance.
    """
    value = str(text or "").strip().lower()
    terms: set[str] = set()
    for token in _ENGLISH_CONCEPT_TOKEN.findall(value):
        if len(token) >= 2:
            terms.add(token)
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", value):
        for index in range(len(chunk) - 1):
            terms.add(chunk[index : index + 2])
    terms.discard("")
    return terms


def claim_binding_terms(text: str) -> set[str]:
    """Distinctive claim concepts that can actually bind a question to a claim."""
    return concept_terms(text) - _GENERIC_CONCEPT_TERMS


def _contradiction_id(statement: str, conflicts_with: str) -> str:
    """Stable identity for an answer contradiction.

    The id depends only on the two normalized phrases, so the same
    statement/conflicts_with pair observed across rounds and sessions maps to
    the same contradiction.  It is not derived from the answer text itself.
    """
    digest = hashlib.sha256(f"{statement}\x00{conflicts_with}".encode()).hexdigest()[:16]
    return f"ctd-{digest}"


def _stable_requirement_id(category: str, text: str, evidence_span: str) -> str:
    digest = hashlib.sha256(f"{category}\n{text}\n{evidence_span}".encode()).hexdigest()[:16]
    return f"req-{digest}"


def validate_job_extraction(raw: dict[str, Any], source_text: str) -> dict[str, Any]:
    """Validate, clamp, map, and deterministically weight an untrusted JD extraction."""

    if not isinstance(raw, dict):
        raise DomainError("invalid_job_extraction", "JD extraction must be a JSON object.")
    source_text = str(source_text or "").strip()
    if not source_text:
        raise DomainError("invalid_job", "JD source text cannot be empty.")
    if len(source_text) > MAX_JOB_CHARS:
        source_text = source_text[:MAX_JOB_CHARS]
    catalog = topic_catalog()
    items = raw.get("requirements")
    if not isinstance(items, list):
        raise DomainError("invalid_job_extraction", "JD extraction requirements must be a list.")

    staged: list[dict[str, Any]] = []
    for item in items[:50]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()[:500]
        category = str(item.get("category") or "").strip()
        if not text or category not in _REQUIREMENT_BASE_WEIGHTS:
            continue
        evidence_span = str(item.get("evidence_span") or "").strip()[:1000]
        if not evidence_span or evidence_span not in source_text:
            evidence_span = text if text in source_text else ""
        if not evidence_span:
            continue
        skills = _string_list_from(item, "skills", limit=20)
        skills = [skill[:128] for skill in skills if len(skill) <= 128]
        topic_ids = _string_list_from(item, "topic_ids", limit=10)
        topic_ids = [topic_id for topic_id in topic_ids if topic_id in catalog]
        deterministic_topics = {topic_id for phrase in [text, *skills] for topic_id in _topics_for_phrase(phrase) if topic_id in catalog}
        topic_ids = list(dict.fromkeys([*topic_ids, *sorted(deterministic_topics)]))[:10]
        expected_level = str(item.get("expected_level") or "unspecified").strip().lower()
        if expected_level not in _EXPECTED_LEVELS:
            expected_level = "unspecified"
        try:
            confidence = max(0.0, min(float(item.get("extraction_confidence", 0)), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0
        repetition = max([source_text.lower().count(skill.lower()) for skill in skills if len(skill.strip()) >= 2] or [1])
        raw_weight = _REQUIREMENT_BASE_WEIGHTS[category] * (1 + min(max(repetition - 1, 0), 5) * 0.1)
        staged.append(
            {
                "requirement_id": _stable_requirement_id(category, text, evidence_span),
                "text": text,
                "category": category,
                "skills": list(dict.fromkeys(skills)),
                "topic_ids": list(dict.fromkeys(topic_ids)),
                "expected_level": expected_level,
                "evidence_span": evidence_span,
                "extraction_confidence": round(confidence, 4),
                "unmapped": not topic_ids,
                "_raw_weight": raw_weight,
            }
        )
    if not staged:
        raise DomainError(
            "invalid_job_extraction",
            "JD extraction did not contain a requirement with a valid source evidence span.",
        )
    total = sum(item["_raw_weight"] for item in staged)
    requirements: list[dict[str, Any]] = []
    for item in staged:
        item["weight"] = round(item.pop("_raw_weight") / total, 6)
        requirements.append(asdict(JDRequirement(**item)))
    return {
        "requirements": requirements,
        "unmapped_requirement_ids": [item["requirement_id"] for item in requirements if item["unmapped"]],
        "extraction_version": JOB_EXTRACTION_VERSION,
    }


def _topics_for_phrase(value: Any) -> set[str]:
    phrase = str(value or "").lower()
    normalized = _normalized_phrase(phrase)
    catalog = topic_catalog()
    topics = {topic_id for topic_id, name in catalog.items() if normalized and (normalized == _normalized_phrase(topic_id) or normalized == _normalized_phrase(name))}
    for alias, mapped in _TECHNOLOGY_TOPIC_ALIASES.items():
        if _normalized_phrase(alias) and _normalized_phrase(alias) in normalized:
            topics.update(topic_id for topic_id in mapped if topic_id in catalog)
    return topics


def match_resume_to_job(resume_extraction: dict[str, Any], job_extraction: dict[str, Any]) -> list[dict[str, Any]]:
    """Match explicit resume evidence first, then record topic inference separately."""

    claims = [item for item in resume_extraction.get("claimed_skills", []) if isinstance(item, dict)]
    stack = [str(item) for item in resume_extraction.get("technology_stack", []) if str(item).strip()]
    projects = [item for item in resume_extraction.get("projects", []) if isinstance(item, dict)]
    results: list[dict[str, Any]] = []
    for requirement in job_extraction.get("requirements", []):
        if not isinstance(requirement, dict):
            continue
        requirement_skills = {_normalized_phrase(item) for item in requirement.get("skills", []) if _normalized_phrase(item)}
        requirement_topics = {str(item) for item in requirement.get("topic_ids", [])}
        evidence: list[dict[str, Any]] = []
        bases: list[str] = []
        claimed_level = None
        inferred_topics: set[str] = set()
        for claim in claims:
            skill = str(claim.get("skill") or "").strip()
            normalized_skill = _normalized_phrase(skill)
            claim_topics = {str(item) for item in claim.get("topics", []) if str(item) in topic_catalog()}
            inferred_topics.update(claim_topics)
            explicit = normalized_skill in requirement_skills or any(normalized_skill and (normalized_skill in requested or requested in normalized_skill) for requested in requirement_skills)
            if explicit:
                evidence.append(
                    {
                        "source": "resume_claim",
                        "text": skill,
                        "claimed_level": str(claim.get("claimed_level") or "familiar"),
                    }
                )
                bases.append("explicit_resume_claim")
                claimed_level = str(claim.get("claimed_level") or "familiar")
            elif requirement_topics & claim_topics:
                evidence.append(
                    {
                        "source": "system_topic_inference",
                        "text": skill,
                        "topic_ids": sorted(requirement_topics & claim_topics),
                    }
                )
                bases.append("deterministic_topic_inference")
        for technology in stack:
            normalized_technology = _normalized_phrase(technology)
            technology_topics = _topics_for_phrase(technology)
            inferred_topics.update(technology_topics)
            if normalized_technology in requirement_skills:
                evidence.append({"source": "resume_stack", "text": technology})
                bases.append("explicit_resume_stack")
            elif requirement_topics & technology_topics:
                evidence.append(
                    {
                        "source": "system_topic_inference",
                        "text": technology,
                        "topic_ids": sorted(requirement_topics & technology_topics),
                    }
                )
                bases.append("deterministic_topic_inference")
        for project in projects:
            project_name = str(project.get("name") or "").strip()
            for skill in project.get("skills", []) or []:
                if _normalized_phrase(skill) in requirement_skills:
                    evidence.append({"source": "resume_project", "text": str(skill), "project": project_name})
                    bases.append("explicit_resume_project")
        explicit = any(base.startswith("explicit_") for base in bases)
        inferred = bool(requirement_topics & inferred_topics) or "deterministic_topic_inference" in bases
        if not requirement_topics:
            match_status = MatchStatus.UNKNOWN.value
        elif explicit:
            match_status = MatchStatus.MATCHED.value
        elif inferred:
            match_status = MatchStatus.PARTIAL.value
        else:
            match_status = MatchStatus.MISSING.value
        category = str(requirement.get("category"))
        risk_level = (
            "critical"
            if category == RequirementCategory.MUST_HAVE.value and match_status == MatchStatus.MISSING.value
            else "high"
            if match_status in {MatchStatus.MISSING.value, MatchStatus.UNKNOWN.value}
            else "medium"
            if match_status == MatchStatus.PARTIAL.value
            else "low"
        )
        results.append(
            asdict(
                RequirementMatch(
                    requirement_id=str(requirement.get("requirement_id")),
                    resume_evidence=evidence[:20],
                    claimed_level=claimed_level,
                    match_status=match_status,
                    risk_level=risk_level,
                    verification_status=VerificationStatus.UNTESTED.value,
                    match_basis=list(dict.fromkeys(bases)),
                )
            )
        )
    return results


def initial_candidate_state(project_attack_map: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Fresh candidate state, optionally seeded with the frozen attack map."""
    state = asdict(
        CandidateState(
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            [],
            "",
            project_attack_map=[dict(item) for item in (project_attack_map or [])],
        )
    )
    state["project_facts"] = []
    state["project_claim_state"] = {
        str(item.get("target_id")): {
            "status": ProjectClaimStatus.UNTESTED.value,
            "attempt_count": int(item.get("attempt_count") or 0),
            "followup_depth": int(item.get("followup_depth") or 0),
            "answered_evidence": [],
            "related_question_ids": [],
        }
        for item in (project_attack_map or [])
        if item.get("target_id")
    }
    return state


def build_initial_interview_plan(
    job_extraction: dict[str, Any],
    matches: list[dict[str, Any]],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    match_by_id = {str(item.get("requirement_id")): item for item in matches}
    default_difficulty = str(profile.get("initial_difficulty") or Difficulty.MEDIUM.value)
    excluded_topics = {str(item) for item in profile.get("excluded_topics", [])}
    focus_topics = [str(item) for item in profile.get("focus_topics", [])]
    items: list[dict[str, Any]] = []
    for requirement in job_extraction.get("requirements", []):
        topics = [str(topic) for topic in requirement.get("topic_ids", []) if str(topic) in topic_catalog() and str(topic) not in excluded_topics]
        if not topics:
            continue
        match = match_by_id.get(str(requirement.get("requirement_id")), {})
        status = str(match.get("match_status") or MatchStatus.UNKNOWN.value)
        risk_multiplier = {
            MatchStatus.MISSING.value: 2.2,
            MatchStatus.UNKNOWN.value: 2.0,
            MatchStatus.PARTIAL.value: 1.7,
            MatchStatus.MATCHED.value: 1.4,
        }[status]
        category_multiplier = 1.25 if requirement.get("category") == RequirementCategory.MUST_HAVE.value else 1.0
        expected_level = str(requirement.get("expected_level") or "unspecified")
        target_difficulty = {
            "junior": Difficulty.BEGINNER.value,
            "beginner": Difficulty.BEGINNER.value,
            "mid": Difficulty.MEDIUM.value,
            "medium": Difficulty.MEDIUM.value,
            "senior": Difficulty.ADVANCED.value,
            "staff": Difficulty.ADVANCED.value,
            "advanced": Difficulty.ADVANCED.value,
        }.get(expected_level, default_difficulty)
        topic_id = next((topic for topic in focus_topics if topic in topics), topics[0])
        focus_multiplier = 1.35 if topic_id in focus_topics else 1.0
        preferred_type = "coding" if topic_id == "algorithm.core" else "scenario" if requirement.get("category") == RequirementCategory.RESPONSIBILITY.value else "theory"
        strategy = PlannerActionKind.VERIFY_RESUME_CLAIM.value if status in {MatchStatus.MATCHED.value, MatchStatus.PARTIAL.value} else PlannerActionKind.VERIFY_JD_REQUIREMENT.value
        # competency_id == topic for this product; must_have mirrors the role
        # capability weight so the planner can guard anchor coverage without
        # reading back any mutable configuration at runtime.
        role_topics = ROLE_CAPABILITY_TREES.get(str(profile.get("target_role") or ""), ())
        topic_weight = next((t.weight for t in role_topics if t.id == topic_id), 0.0)
        plan_item = asdict(
            InterviewPlanItem(
                requirement_id=str(requirement.get("requirement_id")),
                topic_id=topic_id,
                priority=round(
                    float(requirement.get("weight") or 0) * risk_multiplier * category_multiplier * focus_multiplier,
                    6,
                ),
                objective=f"验证 JD 要求：{str(requirement.get('text') or '')[:300]}",
                preferred_question_type=preferred_type,
                target_difficulty=target_difficulty,
                verification_strategy=strategy,
                status="pending",
                attempt_count=0,
                competency_id=topic_id,
                must_have=topic_weight >= 1.2,
            )
        )
        # Decompose priority into its JD factors so planner decisions can be
        # audited per term (jd_weight * risk * category * focus = priority).
        plan_item["jd_weight"] = round(float(requirement.get("weight") or 0), 6)
        plan_item["risk_multiplier"] = risk_multiplier
        plan_item["category_multiplier"] = category_multiplier
        plan_item["focus_multiplier"] = focus_multiplier
        items.append(plan_item)
    items.sort(key=lambda item: (-float(item["priority"]), item["requirement_id"], item["topic_id"]))
    if not items:
        raise DomainError("no_mapped_requirements", "The JD has no requirements mapped to the interview topic catalog.", http_status=409)
    return items


_DIMENSION_TIME_COST: dict[str, float] = {
    "implementation": 0.15,
    "selection": 0.20,
    "failure": 0.30,
    "tradeoff": 0.25,
    "data": 0.20,
    "interface": 0.15,
    "metric": 0.25,
    "testing": 0.15,
}


def _claim_risk_base(claim: dict[str, Any]) -> float:
    flags = {str(item) for item in (claim.get("risk_flags") or [])}
    if flags & {"vague_metric", "missing_validation", "happy_path_only"}:
        return 0.9
    if flags & {"unexplained_choice", "keyword_stacking"}:
        return 0.75
    return 0.55


def _claim_jd_binding(claim: dict[str, Any], requirements: list[dict[str, Any]], project_skills: list[str] | None = None) -> tuple[str | None, str, float]:
    """Best (requirement_id, topic_id, jd_weight) a project claim binds to.

    Explicit claim topic overlap wins; otherwise project skills are mapped
    through the deterministic technology alias table so a claim can still
    ground a question on a known topic.
    """
    catalog = topic_catalog()
    claim_topics = {str(item) for item in (claim.get("topic_ids") or []) if str(item) in catalog}
    claim_skills = {_normalized_phrase(item) for item in (claim.get("skills") or []) if str(item).strip()}
    project_topics = {topic for topic in _topics_for_skills(list(project_skills or [])) if topic in catalog}
    all_topics = claim_topics or project_topics
    best_req: str | None = None
    best_topic = ""
    best_weight = 0.0
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        req_topics = {str(item) for item in (requirement.get("topic_ids") or []) if str(item) in catalog}
        req_skills = {_normalized_phrase(item) for item in (requirement.get("skills") or []) if str(item).strip()}
        hit_topics = all_topics & req_topics
        hit_skills = claim_skills & req_skills
        if not (hit_topics or hit_skills):
            continue
        weight = float(requirement.get("weight") or 0)
        if weight > best_weight:
            best_weight = weight
            best_req = str(requirement.get("requirement_id") or "") or None
            best_topic = next(iter(sorted(hit_topics)), None) or next(iter(sorted(req_topics)), "") or ""
    if not best_topic and all_topics:
        best_topic = next(iter(sorted(all_topics)))
    return best_req, best_topic, best_weight


def _topics_for_skills(skills: list[str]) -> set[str]:
    topics: set[str] = set()
    for skill in skills:
        topics.update(_topics_for_phrase(skill))
    return topics


def inspect_claim_mechanism(claim_text: str) -> str:
    """Deterministically extract the concrete mechanism a claim asserts.

    Strips leading solution verbs (通过/采用/基于/利用/借助/使用) and cuts at the
    first achievement/result marker (实现/保证/确保/降低/提升/提高/达到/支撑...)
    so the returned phrase names the *mechanism* ("Redis Lua 租约、ACK Deadline
    和 Kafka") rather than the outcome ("实现可靠投递").
    """
    text = str(claim_text or "").strip()
    text = re.sub(r"^(通过|采用|基于|利用|借助|使用|运用|借助)", "", text).strip("：:，,。 ")
    marker = re.search(r"(实现|保证|确保|降低|提升|提高|达到|完成|减少|优化|支撑|支持|使|从而|以此|确保)", text)
    if marker:
        text = text[: marker.start()].strip("，,。 ；; ")
    return text[:80] or str(claim_text or "")[:80]


def _rubric_points_for_dimension(dimension: str, mechanism: str, concepts: set[str]) -> list[dict[str, Any]]:
    """Claim-specific rubric points for one attack dimension."""
    topics = "、".join(sorted(concepts)[:5])
    mechanism_hint = mechanism if len(mechanism) <= 60 else mechanism[:57] + "…"
    base = [
        {
            "point": f"解释你在项目中实现“{mechanism_hint}”的具体做法（模块、代码边界、你亲手写的部分），而不是复述通用原理。",
            "kind": "self_implementation",
        },
        {
            "point": f"说明关键数据流与状态变化：围绕“{mechanism_hint}”，一次请求/故障中数据如何流转、状态在何时何地变更。",
            "kind": "data_flow",
        },
        {
            "point": f"覆盖本维度：{_PROJECT_DIMENSION_DESCRIPTIONS.get(dimension, dimension)}。",
            "kind": "dimension_coverage",
        },
        {
            "point": f"说明对应技术原理（{topics} 背后的原理、边界与常见误区），原理必须落到该项目实际用到的机制上。",
            "kind": "technical_understanding",
        },
        {
            "point": "给出验证方法：测试、指标、日志或压测中的任意一项能证明该声明真实发生，而不是推测。",
            "kind": "validation_method",
        },
    ]
    dimension_points = {
        "failure": {
            "point": f"描述“{mechanism_hint}”下一次故障窗口的恢复过程（写入成功但后续 ACK/提交失败时如何避免重复或丢失）。",
            "kind": "failure_window",
        },
        "metric": {
            "point": "说明指标基线：提升前的数值、测量口径与统计周期，避免只报一个孤立的最终数字。",
            "kind": "metric_baseline",
        },
        "metric_control": {
            "point": "说明变量控制：同一对比条件下排除了哪些干扰因素（机器、流量、缓存、样本量）。",
            "kind": "metric_variable_control",
        },
        "metric_measurement": {
            "point": "说明测量方法：如何采样、统计与复现该指标，误差范围或置信度如何。",
            "kind": "metric_measurement",
        },
        "selection": {
            "point": f"对比备选方案并说明为什么选择“{mechanism_hint}”而不是替代方案（量化依据或约束条件）。",
            "kind": "alternatives",
        },
        "tradeoff": {
            "point": f"说明“{mechanism_hint}”的主要取舍（一致性/可用性/成本/复杂度），以及你接受与放弃了什么。",
            "kind": "tradeoff",
        },
    }
    if dimension == "metric":
        base.extend(
            [
                dimension_points["metric"],
                dimension_points["metric_control"],
                dimension_points["metric_measurement"],
            ]
        )
    elif dimension in dimension_points:
        base.append(dimension_points[dimension])
    return base


def build_claim_specific_rubric(
    claim_type: str,
    dimension: str,
    core_concepts: Iterable[str],
    inspected_mechanism: str,
) -> list[dict[str, Any]]:
    """Deterministically build the claim/dimension-specific evaluation rubric.

    Unlike the generic competency rubric (go.runtime / redis), every point here
    is bound to the resume claim's own mechanism and the attack dimension, and
    is emitted as structured ``{point, kind}`` rows the judge can score against.
    """
    concepts = {str(item) for item in core_concepts if str(item).strip()}
    points = _rubric_points_for_dimension(dimension, inspected_mechanism, concepts)
    label = _CLAIM_TYPE_LABELS.get(str(claim_type or ""), "机制")
    points.append(
        {
            "point": f"该回答是否真正验证简历中的{label}声明“{inspected_mechanism}”（给出你自己的实现细节），而非仅展示对相关技术的理解。",
            "kind": "claim_verification",
        }
    )
    return points


@dataclass(frozen=True)
class ProjectQuestionContract:
    """Deterministic binding between a generated question and a resume claim.

    A project-type question may ONLY be generated when a complete contract
    exists: every field below must be non-empty (see
    :func:`validate_project_question_contract`).  ``core_concepts`` are the
    normalized claim/technology terms used for evidence relevance and question
    binding; ``evidence_chunk_ids`` are the chunks that passed the claim-level
    relevance check; ``claim_specific_rubric`` is the per-claim scoring rubric.
    """

    project_id: str
    project_name: str
    claim_id: str
    claim_text: str
    claim_type: str
    project_dimension: str
    core_concepts: tuple[str, ...]
    evidence_chunk_ids: tuple[str, ...]
    inspected_mechanism: str
    claim_specific_rubric: tuple[dict[str, Any], ...]


def build_project_question_contract(
    project: dict[str, Any],
    claim: dict[str, Any],
    dimension: str,
    evidence: list[dict[str, Any]],
) -> ProjectQuestionContract:
    """Build the frozen contract for one attack target from the resume claim.

    Evidence is optional at construction time (the pipeline fills it after
    retrieval); a contract with empty evidence is not usable for a question and
    must fail :func:`validate_project_question_contract` until claim-relevant
    evidence is bound.
    """
    claim_text = str(claim.get("text") or "")
    core = concept_terms(claim_text)
    core.update(concept_terms(str(project.get("name") or "")))
    for skill in [*(claim.get("skills") or []), *(project.get("skills") or [])]:
        core.update(concept_terms(str(skill)))
    inspected = inspect_claim_mechanism(claim_text)
    rubric = build_claim_specific_rubric(
        str(claim.get("claim_type") or "mechanism"),
        dimension,
        core,
        inspected,
    )
    return ProjectQuestionContract(
        project_id=str(project.get("project_id") or ""),
        project_name=str(project.get("name") or ""),
        claim_id=str(claim.get("claim_id") or ""),
        claim_text=claim_text,
        claim_type=str(claim.get("claim_type") or "mechanism"),
        project_dimension=str(dimension or ""),
        core_concepts=tuple(sorted(core)),
        evidence_chunk_ids=tuple(str(item.get("evidence_id") or "") for item in evidence if item.get("evidence_id")),
        inspected_mechanism=inspected,
        claim_specific_rubric=tuple(rubric),
    )


def validate_project_question_contract(contract: ProjectQuestionContract, *, evidence_required: bool = True) -> dict[str, Any]:
    """Raise when a project question cannot be deterministically bound.

    Any missing key field, an unknown dimension, empty core concepts, missing
    claim-relevant evidence or fewer than three rubric points prevents a
    ``project`` question from being generated.
    """
    required = ("project_id", "project_name", "claim_id", "claim_text", "claim_type", "project_dimension", "inspected_mechanism")
    missing = [name for name in required if not str(getattr(contract, name) or "").strip()]
    if contract.project_dimension not in PROJECT_DIMENSIONS:
        missing.append("project_dimension")
    if not contract.core_concepts:
        missing.append("core_concepts")
    if evidence_required and not contract.evidence_chunk_ids:
        missing.append("evidence_chunk_ids")
    rubric_points = [item for item in (contract.claim_specific_rubric or ()) if isinstance(item, dict) and str(item.get("point") or "").strip()]
    if len(rubric_points) < 3:
        missing.append("claim_specific_rubric")
    if missing:
        raise DomainError("invalid_project_contract", f"Project question contract is incomplete: {', '.join(missing)}")
    return {"valid": True, "rubric_point_count": len(rubric_points), "binding_terms": sorted(claim_binding_terms(contract.claim_text))}


def _claim_specific_match(text: str, claim_text: str) -> tuple[bool, set[str], set[str]]:
    """Deterministic (is_specific, shared, strong_shared) for a claim vs a fact.

    ``distinctive`` = claim concepts minus generic words; ``strong`` further
    excludes broad technology names (redis/kafka/go/...).  A text is claim-
    specific when it co-occurs with at least two distinctive concepts OR with
    at least one strong mechanism concept (e.g. "租约", "lua", "checkpoint",
    "ack") -- "Kafka 分区顺序" alone never is, because "kafka" is only the
    broad topic, not the candidate's implementation.
    """
    distinctive = claim_binding_terms(claim_text)
    if not distinctive:
        return False, set(), set()
    shared = concept_terms(str(text or "")) & distinctive
    strong = shared - _BROAD_TECHNOLOGY_TERMS
    # A fact that only co-occurs with broad technology names (kafka+redis) is
    # the broad topic, not the claim's mechanism.  At least one strong concept
    # (a mechanism word such as 租约 / lua / checkpoint / ack / 分桶) must appear.
    specific = bool(strong)
    return specific, shared, strong


def claim_specific_overlap(text: str, claim_text: str) -> dict[str, Any]:
    """Public deterministic claim-overlap result for pipeline gates."""
    specific, shared, strong = _claim_specific_match(text, claim_text)
    return {"specific": specific, "shared": shared, "strong": strong}


def validate_project_evidence(
    evidence: list[dict[str, Any]],
    contract: ProjectQuestionContract,
    *,
    min_shared_concepts: int = 2,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split evidence into claim-relevant and claim-irrelevant chunks.

    ``min_shared_concepts`` distinctive claim concepts must co-occur in the
    chunk (or one strong mechanism concept must appear), otherwise the chunk is
    only "same broad topic" (e.g. a context.Context doc for a Redis Lua/Kafka
    reliability claim) and must not ground a project question.  The claim's own
    mechanism phrase is a backstop: a chunk containing it verbatim is accepted
    even when token overlap is thin.
    """
    distinctive = claim_binding_terms(contract.claim_text)
    if not distinctive:
        return list(evidence), []
    mechanism_norm = _normalized_phrase(contract.inspected_mechanism)
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for item in evidence:
        content = str(item.get("content") or "")
        specific, shared, strong = _claim_specific_match(content, contract.claim_text)
        relevance = round(len(shared) / len(distinctive), 4)
        normalized_content = _normalized_phrase(content)
        verbatim = bool(mechanism_norm) and mechanism_norm in normalized_content
        # The chunk must reference the claim's strong mechanism concepts (or
        # the mechanism phrase verbatim); broad-topic-only chunks (context docs,
        # generic Kafka/Redis notes) are claim-irrelevant even when they share
        # technology names.  ``min_shared_concepts`` stays as the floor on the
        # distinctive-concept co-occurrence for lenient corpora.
        dimension_relevant = matches_project_dimension(content, contract.project_dimension)
        if dimension_relevant and (specific or verbatim or (bool(strong) and len(shared) >= min_shared_concepts)):
            accepted.append(
                {
                    **item,
                    "claim_relevance": relevance,
                    "shared_concepts": sorted(shared),
                    "claim_relevant": True,
                    "dimension_relevant": True,
                }
            )
        else:
            rejected.append(
                {
                    **item,
                    "claim_relevance": relevance,
                    "shared_concepts": sorted(shared),
                    "claim_relevant": False,
                    "dimension_relevant": dimension_relevant,
                    "reason": "claim_irrelevant" if not (specific or verbatim) else "dimension_irrelevant",
                }
            )
    return accepted, rejected


def claim_specific_evidence(
    evidence: Iterable[dict[str, Any]],
    claim_text: str,
) -> list[dict[str, Any]]:
    """Facts/evidence spans that actually reference the resume claim's mechanism.

    Used by ``update_project_claim_state`` so an answer that only restates
    generic Kafka/Redis principles can never mark the claim ``verified``.
    """
    result = []
    for item in evidence:
        # Only the exact answer quote is authoritative. ``fact`` is an LLM
        # summary and may paraphrase or hallucinate claim terminology that the
        # candidate never said; it must never promote a resume claim.
        text = str(item.get("evidence_span") or "")
        specific, _shared, _strong = _claim_specific_match(text, claim_text)
        if specific:
            result.append(item)
    return result


def build_project_attack_map(
    resume_snapshot: dict[str, Any],
    job_extraction: dict[str, Any],
    profile: dict[str, Any] | None = None,
    *,
    max_dimensions: int = 4,
    max_targets: int = 8,
) -> list[dict[str, Any]]:
    """Deterministically build the frozen project attack map for a session.

    One main project (the one with the highest JD relevance) covers 3-4
    effective dimensions -- never every dimension mechanically.  Each target
    carries a frozen ``priority`` computed from JD weight * claim risk *
    dimension information gain * verification uncertainty minus a dimension
    time cost, so identical inputs always produce the identical attack map.

    Must-have competency anchors are not part of this map: the planner keeps
    them on the JD plan and only lets project questions compete once the anchor
    baseline is complete.
    """
    projects = [item for item in (resume_snapshot or {}).get("projects", []) if isinstance(item, dict) and item.get("project_id") and item.get("claims")]
    if not projects:
        return []
    requirements = [item for item in (job_extraction or {}).get("requirements", []) if isinstance(item, dict)]
    catalog = topic_catalog()

    ranked: list[tuple[dict[str, Any], float, dict[str, tuple[str | None, str, float]]]] = []
    for project in projects:
        bindings: dict[str, tuple[str | None, str, float]] = {}
        touched: set[str] = set()
        for claim in (project.get("claims") or []):
            if not isinstance(claim, dict) or not claim.get("claim_id"):
                continue
            binding = _claim_jd_binding(claim, requirements, project.get("skills"))
            bindings[str(claim["claim_id"])] = binding
            if binding[0]:
                touched.add(binding[0])
        # Project-level skills also touch JD requirements (the candidate used
        # these technologies on the project even when a specific claim is about
        # something else), so the most JD-relevant project wins deterministically.
        for skill in (project.get("skills") or []):
            for topic in _topics_for_phrase(skill):
                for requirement in requirements:
                    if topic in (requirement.get("topic_ids") or []) and requirement.get("requirement_id"):
                        touched.add(str(requirement["requirement_id"]))
        total = sum(float(requirement.get("weight") or 0) for requirement in requirements if str(requirement.get("requirement_id") or "") in touched)
        ranked.append((project, round(total, 6), bindings))
    ranked.sort(key=lambda item: (-item[1], str(item[0].get("project_id") or "")))
    main_project, _relevance, main_bindings = ranked[0]

    candidates: list[dict[str, Any]] = []
    for claim in (main_project.get("claims") or []):
        if not isinstance(claim, dict) or not claim.get("claim_id"):
            continue
        claim_id = str(claim["claim_id"])
        requirement_id, topic_id, jd_weight = main_bindings.get(claim_id, (None, "", 0.0))
        if not topic_id or topic_id not in catalog:
            continue
        flags = {str(item) for item in (claim.get("risk_flags") or [])}
        for dimension in DIMENSIONS_BY_CLAIM_TYPE.get(str(claim.get("claim_type") or "mechanism"), ("implementation",)):
            target_id = f"{main_project['project_id']}::{claim_id}::{dimension}"
            risk = _claim_risk_base(claim)
            time_cost = _DIMENSION_TIME_COST[dimension]
            # Risk-driven probing: a happy-path-only claim is probed on failure
            # first, a vague metric on metric, an unexplained choice on
            # selection/trade-off.  The boosted gain makes the risky dimension
            # the first attack target without ever fabricating a dimension.
            gain = 0.9
            if dimension == "failure" and "happy_path_only" in flags or dimension == "metric" and flags & {"vague_metric", "missing_validation"}:
                gain = 1.2
            elif dimension in {"selection", "tradeoff"} and "unexplained_choice" in flags:
                gain = 1.1
            priority = round((0.6 + 0.4 * jd_weight) * risk * gain * 0.85 - time_cost, 6)
            candidates.append(
                {
                    "target_id": target_id,
                    "project_id": main_project["project_id"],
                    "project_name": str(main_project.get("name") or ""),
                    "claim_id": claim_id,
                    "claim_type": str(claim.get("claim_type") or "mechanism"),
                    "claim_text": str(claim.get("text") or "")[:500],
                    "dimension": dimension,
                    "topic_id": topic_id,
                    "jd_requirement_id": requirement_id,
                    "priority": priority,
                    "status": "pending",
                    "attempt_count": 0,
                    "followup_depth": 0,
                }
            )

    candidates.sort(key=lambda item: (-float(item["priority"]), str(item["target_id"])))
    selected: list[dict[str, Any]] = []
    dimension_counts: dict[str, int] = defaultdict(int)
    claim_counts: dict[str, int] = defaultdict(int)

    def _fits(candidate: dict[str, Any]) -> bool:
        dimension = candidate["dimension"]
        within_targets = len(selected) < max_targets
        within_claim_cap = claim_counts[candidate["claim_id"]] < PROJECT_CLAIM_MAX_FOLLOWUPS + 1
        within_dimension_diversity = dimension in dimension_counts or len(dimension_counts) < max_dimensions
        return within_targets and within_claim_cap and within_dimension_diversity

    for candidate in candidates:
        if _fits(candidate):
            selected.append(candidate)
            dimension_counts[candidate["dimension"]] += 1
            claim_counts[candidate["claim_id"]] += 1

    # If the greedy pass left fewer than 3 dimensions (some claims are thin),
    # widen with the best remaining candidate from a missing dimension.
    if len(dimension_counts) < 3 and len(selected) < max_targets:
        for candidate in candidates:
            if candidate in selected or len(selected) >= max_targets:
                continue
            if candidate["dimension"] not in dimension_counts:
                selected.append(candidate)
                dimension_counts[candidate["dimension"]] += 1
                claim_counts[candidate["claim_id"]] += 1
    selected.sort(key=lambda item: (-float(item["priority"]), str(item["target_id"])))
    return selected[:max_targets]


def _exact_answer_span(value: Any, answer: str, *, limit: int = 500) -> str:
    span = str(value or "").strip()[:limit]
    return span if span and span in answer else ""


def validate_answer_state(
    raw: dict[str, Any],
    answer: str,
    known_claims: Iterable[str] = (),
    known_project_claims: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate answer-derived claims without treating them as technical truth.

    ``known_project_claims`` maps claim_id -> project_id for the claims frozen
    in the session attack map.  A project_fact is only allowed to keep its
    attribution when the claim actually belongs to the reported project, so a
    mechanism mentioned in one project's answer can never be chained to another
    project's claim.
    """

    if not isinstance(raw, dict):
        raise DomainError("invalid_answer_state", "Answer state extraction must be a JSON object.")
    catalog = topic_catalog()
    known = "\n".join(str(item) for item in known_claims if str(item).strip()).lower()

    def facts(name: str, text_key: str) -> list[dict[str, Any]]:
        result = []
        values = raw.get(name, [])
        if not isinstance(values, list):
            return result
        for item in values[:30]:
            if not isinstance(item, dict):
                continue
            text = str(item.get(text_key) or "").strip()[:500]
            span = _exact_answer_span(item.get("evidence_span"), answer)
            if not text or not span:
                continue
            topics = [str(topic) for topic in item.get("topic_ids", []) if str(topic) in catalog]
            result.append({text_key: text, "topic_ids": list(dict.fromkeys(topics)), "evidence_span": span})
        return result

    def project_facts() -> list[dict[str, Any]]:
        result = []
        values = raw.get("project_facts", [])
        if not isinstance(values, list):
            return result
        for item in values[:30]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("fact") or "").strip()[:500]
            span = _exact_answer_span(item.get("evidence_span"), answer)
            if not text or not span:
                continue
            topics = [str(topic) for topic in item.get("topic_ids", []) if str(topic) in catalog]
            project_id = str(item.get("project_id") or "").strip()
            claim_id = str(item.get("claim_id") or "").strip()
            fact_kind = str(item.get("fact_kind") or "mechanism").strip().lower()
            if fact_kind not in PROJECT_FACT_KINDS:
                fact_kind = "mechanism"
            if project_id and claim_id and known_project_claims and (claim_id not in known_project_claims or known_project_claims[claim_id] != project_id):
                # Attribution survives only when the claim truly belongs to the
                # reported project; anything else loses its ownership so no
                # fact can leak across projects.
                project_id, claim_id = "", ""
            result.append(
                {
                    "fact": text,
                    "fact_kind": fact_kind,
                    "project_id": project_id,
                    "claim_id": claim_id,
                    "topic_ids": list(dict.fromkeys(topics)),
                    "evidence_span": span,
                }
            )
        return result

    contradictions = []
    values = raw.get("contradictions", [])
    if isinstance(values, list):
        for item in values[:20]:
            if not isinstance(item, dict):
                continue
            statement = str(item.get("statement") or "").strip()[:500]
            conflicts_with = str(item.get("conflicts_with") or "").strip()[:500]
            span = _exact_answer_span(item.get("evidence_span"), answer)
            if not statement or not conflicts_with or not span or _normalized_phrase(conflicts_with) not in _normalized_phrase(known):
                continue
            try:
                confidence = max(0.0, min(float(item.get("confidence", 0)), 1.0))
            except (TypeError, ValueError):
                confidence = 0.0
            topics = [str(topic) for topic in item.get("topic_ids", []) if str(topic) in catalog]
            contradictions.append(
                {
                    "contradiction_id": _contradiction_id(statement, conflicts_with),
                    "statement": statement,
                    "conflicts_with": conflicts_with,
                    "topic_ids": list(dict.fromkeys(topics)),
                    "evidence_span": span,
                    "confidence": round(confidence, 4),
                    "status": "unresolved",
                }
            )

    def strings(name: str, limit: int = 30) -> list[str]:
        value = raw.get(name, [])
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(str(item).strip()[:500] for item in value if str(item).strip()))[:limit]

    return {
        "technical_concepts": facts("technical_concepts", "concept"),
        "newly_claimed_facts": facts("newly_claimed_facts", "fact"),
        "project_facts": project_facts(),
        "contradictions": contradictions,
        "covered_rubric_points": strings("covered_rubric_points"),
        "unverified_boundaries": strings("unverified_boundaries"),
        "deep_dive_branches": facts("deep_dive_branches", "branch"),
        "answer_state_version": ANSWER_STATE_VERSION,
    }


def _contradiction_identity(item: dict[str, Any]) -> str:
    """Return the stable contradiction id, computing it lazily for v1 rows."""
    cid = str(item.get("contradiction_id") or "").strip()
    if cid:
        return cid
    return _contradiction_id(str(item.get("statement") or ""), str(item.get("conflicts_with") or ""))


def update_project_claim_state(
    state: dict[str, Any],
    answer_state: dict[str, Any],
    judge: JudgeResult,
    project_target: dict[str, Any] | None,
    *,
    required_score: int,
    completed: bool = True,
    confidence_threshold: float = 0.7,
    question_id: str = "",
) -> dict[str, Any]:
    """Update the verification status of the current target project claim.

    Only ``project_target`` (the claim/dimension explicitly pursued by the
    round) is updated -- a good score on a same-topic question never verifies a
    different claim.  ``verified`` additionally requires project-claim-relevant
    evidence (a project_fact attributed to this claim), so technical skill and
    claim truthfulness stay separate signals.  New facts introduced by the
    answer only become pending facts (state["project_facts"]), never verified
    in the same round.
    """
    result = dict(state)
    if not project_target:
        return result
    project_id = str(project_target.get("project_id") or "")
    claim_id = str(project_target.get("claim_id") or "")
    dimension = str(project_target.get("dimension") or "")
    claim_text = str(project_target.get("claim_text") or "")[:500]
    question_id = str(project_target.get("question_id") or "") or question_id
    if not project_id or not claim_id or not dimension:
        return result
    target_id = f"{project_id}::{claim_id}::{dimension}"
    claim_states = dict(result.get("project_claim_state") or {})
    row = dict(claim_states.get(target_id) or {})
    row["attempt_count"] = int(row.get("attempt_count") or 0) + 1
    if question_id:
        related = list(row.get("related_question_ids") or [])
        if question_id not in related:
            related.append(question_id)
        row["related_question_ids"] = related[-20:]

    # Project-claim-relevant answer evidence: facts the extractor attributed to
    # this exact claim.  A mechanism from a different project/claim does not
    # count (no cross-project chaining).
    attributed = [
        item
        for item in answer_state.get("project_facts", [])
        if str(item.get("claim_id") or "") == claim_id and (not str(item.get("project_id") or "") or str(item.get("project_id")) == project_id)
    ]
    evidence = list(row.get("answered_evidence") or [])
    seen = {(_normalized_phrase(str(item.get("fact") or "")), _normalized_phrase(str(item.get("evidence_span") or ""))) for item in evidence}
    for item in attributed:
        marker = (_normalized_phrase(str(item.get("fact") or "")), _normalized_phrase(str(item.get("evidence_span") or "")))
        if marker in seen:
            continue
        seen.add(marker)
        evidence.append(
            {
                "fact": str(item.get("fact") or "")[:500],
                "fact_kind": str(item.get("fact_kind") or "mechanism"),
                "evidence_span": str(item.get("evidence_span") or "")[:500],
            }
        )
    row["answered_evidence"] = evidence[-20:]

    contradicted = False
    contradiction_id = ""
    claim_norm = _normalized_phrase(claim_text)
    for contradiction in answer_state.get("contradictions", []):
        conflict = _normalized_phrase(str(contradiction.get("conflicts_with") or ""))
        if conflict and claim_norm and (conflict in claim_norm or claim_norm in conflict):
            contradicted = True
            contradiction_id = str(contradiction.get("contradiction_id") or "")
            break
    # Claim-specific evidence: across ALL attempts of this claim, at least one
    # fact/span must reference the claim's own mechanism.  A high score from a
    # generic Kafka/Redis/Go explanation earns technical credit but can never
    # promote the claim to ``verified``.
    specific_evidence = claim_specific_evidence(evidence, claim_text)
    row["claim_specific_evidence_count"] = len(specific_evidence)
    if contradicted:
        row["status"] = ProjectClaimStatus.CONTRADICTION.value
        if contradiction_id:
            row["contradiction_id"] = contradiction_id
    elif not completed:
        row["status"] = ProjectClaimStatus.PARTIAL.value
    elif judge.score <= 1:
        row["status"] = ProjectClaimStatus.DISPUTED.value
    elif judge.confidence < 0.4:
        row["status"] = ProjectClaimStatus.LOW_CONFIDENCE.value
    elif (
        judge.score >= required_score
        and judge.confidence >= confidence_threshold
        and judge.technical_understanding >= 2
        and judge.claim_verification == "verified"
        and specific_evidence
    ):
        row["status"] = ProjectClaimStatus.VERIFIED.value
    else:
        row["status"] = ProjectClaimStatus.PARTIAL.value
    row["followup_depth"] = min(max(int(row.get("followup_depth") or 0), int(project_target.get("followup_depth") or 0)), PROJECT_CLAIM_MAX_FOLLOWUPS)
    claim_states[target_id] = row
    result["project_claim_state"] = claim_states
    return result


def merge_candidate_state(
    state: dict[str, Any],
    answer_state: dict[str, Any],
    judge: JudgeResult,
    *,
    requirement_id: str | None,
    target_topic: str,
    completed: bool,
    required_score: int = 3,
    targeted_claim_facts: Iterable[str] = (),
    resolved_contradiction_ids: Iterable[str] = (),
    project_target: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {**initial_candidate_state(), **(state or {})}

    def extend_unique(name: str, values: Iterable[Any], key) -> None:
        current = list(result.get(name) or [])
        seen = {key(item) for item in current}
        for item in values:
            marker = key(item)
            if marker not in seen:
                current.append(item)
                seen.add(marker)
        result[name] = current[:100]

    # A fact introduced by the current answer remains a claim. Only a claim
    # already present before this answer can become verified/disputed here.
    # Project facts are tracked separately with their project/claim ownership:
    # they must be able to trigger a project follow-up and must never be
    # flattened into ordinary newly_claimed_facts.
    prior_unverified_facts = list(result.get("newly_claimed_facts") or [])
    new_facts = list(answer_state.get("newly_claimed_facts", []))
    extend_unique("newly_claimed_facts", new_facts, lambda item: _normalized_phrase(item.get("fact")))
    extend_unique(
        "project_facts",
        list(answer_state.get("project_facts", [])),
        lambda item: (_normalized_phrase(item.get("fact")), str(item.get("project_id") or ""), str(item.get("claim_id") or "")),
    )
    # Contradictions are deduplicated by stable id, and only the contradiction
    # that was explicitly pursued in this round may be resolved.  Same-topic
    # siblings stay unresolved so they can be clarified separately later.
    # Every stored row is normalized so it always carries a contradiction_id
    # (v1 answer-state rows lack it and get one computed lazily here).
    resolved_ids = {str(item) for item in resolved_contradiction_ids if str(item).strip()}
    merged_contradictions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in [*(result.get("contradictions") or []), *answer_state.get("contradictions", [])]:
        identity = _contradiction_identity(item)
        if identity in seen_ids:
            continue
        seen_ids.add(identity)
        merged_contradictions.append({**item, "contradiction_id": identity})
    result["contradictions"] = [
        {**item, "status": "resolved" if item["contradiction_id"] in resolved_ids else item.get("status", "unresolved")}
        for item in merged_contradictions[:100]
    ]
    hypotheses = [{"text": text, "topic_ids": [target_topic], "source": "answer_boundary"} for text in answer_state.get("unverified_boundaries", [])] + [
        {"text": item.get("branch"), "topic_ids": item.get("topic_ids", []), "source": "answer_branch"} for item in answer_state.get("deep_dive_branches", [])
    ]
    extend_unique("unanswered_hypotheses", hypotheses, lambda item: (_normalized_phrase(item.get("text")), tuple(item.get("topic_ids", []))))
    if judge.weak_point:
        extend_unique("weak_points", [judge.weak_point], _normalized_phrase)
    targeted_claim_keys = {_normalized_phrase(item) for item in targeted_claim_facts if _normalized_phrase(item)}
    targeted_prior_facts = [item for item in prior_unverified_facts if _normalized_phrase(item.get("fact")) in targeted_claim_keys]
    if completed and judge.score >= required_score:
        extend_unique("strong_points", [target_topic], _normalized_phrase)
        extend_unique("verified_facts", targeted_prior_facts, lambda item: _normalized_phrase(item.get("fact")))
        verified_keys = {_normalized_phrase(item.get("fact")) for item in targeted_prior_facts}
        result["newly_claimed_facts"] = [item for item in result["newly_claimed_facts"] if _normalized_phrase(item.get("fact")) not in verified_keys]
    elif completed and judge.score <= 1:
        extend_unique("disputed_facts", targeted_prior_facts, lambda item: _normalized_phrase(item.get("fact")))
        disputed_keys = {_normalized_phrase(item.get("fact")) for item in targeted_prior_facts}
        result["newly_claimed_facts"] = [item for item in result["newly_claimed_facts"] if _normalized_phrase(item.get("fact")) not in disputed_keys]
    if completed and requirement_id:
        result["covered_requirement_ids"] = list(dict.fromkeys([*(result.get("covered_requirement_ids") or []), requirement_id]))
    # Every answered project turn contributes evidence and consumes one attempt,
    # including intermediate follow-ups.  ``completed`` only controls the JD
    # requirement/ordinary-claim lifecycle above; project truthfulness has its
    # own state machine and must not discard evidence between follow-ups.
    if project_target:
        result = update_project_claim_state(
            result,
            answer_state,
            judge,
            project_target,
            required_score=required_score,
            completed=completed,
            question_id=str(project_target.get("question_id") or ""),
        )
    return result


def update_interview_plan(
    plan: list[dict[str, Any]],
    requirement_id: str | None,
    *,
    score: int | None,
    completed: bool,
    required_score: int = 3,
) -> list[dict[str, Any]]:
    updated = []
    for item in plan:
        row = dict(item)
        if requirement_id and row.get("requirement_id") == requirement_id:
            row["attempt_count"] = int(row.get("attempt_count") or 0) + 1
            if completed:
                row["status"] = "verified" if score is not None and score >= required_score else "partial" if score is not None and score >= 2 else "disputed"
            else:
                row["status"] = "in_progress"
        updated.append(row)
    return updated


def _planner_input_hashes(plan: list[dict[str, Any]], candidate_state: dict[str, Any], rounds: list[dict[str, Any]], competency_snapshot: dict[str, Any] | None = None) -> dict[str, str]:
    hashes = {
        "plan_hash": payload_hash({"plan": plan}),
        "candidate_state_hash": payload_hash({"candidate_state": candidate_state}),
        "rounds_hash": payload_hash({"rounds": rounds}),
    }
    if competency_snapshot is not None:
        hashes["competency_snapshot_hash"] = payload_hash({"competency_snapshot": competency_snapshot})
    return hashes


def _required_score_for(competency_snapshot: dict[str, Any] | None, competency_id: str) -> int:
    rubric = ((competency_snapshot or {}).get("rubrics") or {}).get(competency_id) or {}
    try:
        return max(2, min(4, int(rubric.get("required_score") or 3)))
    except (TypeError, ValueError):
        return 3


def _evidence_summary(rounds: list[dict[str, Any]], competency_snapshot: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    """Per-competency evidence derived only from persisted rounds.

    ``anchor_done`` means at least one anchor round scored >=3 with confidence
    at or above ANCHOR_CONFIDENCE_THRESHOLD. ``high_conf_evidence`` counts all
    high-confidence scores >=3 so the planner can lower the priority of a
    competency that already has strong evidence.
    """
    summary: dict[str, dict[str, Any]] = {}
    for row in rounds:
        if row.get("status") != RoundStatus.COMPLETED.value:
            continue
        competency_id = str(row.get("competency_id") or "")
        if not competency_id:
            continue
        entry = summary.setdefault(competency_id, {"anchor_done": False, "anchor_attempted": False, "high_conf_evidence": 0, "scores": []})
        score = row.get("score")
        if score is not None:
            entry["scores"].append(float(score))
        if row.get("question_kind") == "anchor":
            entry["anchor_attempted"] = True
        confidence = float(row.get("judge_confidence") or 0)
        required_score = _required_score_for(competency_snapshot, competency_id)
        high_confidence = score is not None and float(score) >= required_score and confidence >= ANCHOR_CONFIDENCE_THRESHOLD and not _round_low_confidence(row)
        if row.get("question_kind") == "anchor" and high_confidence:
            entry["anchor_done"] = True
        if high_confidence:
            entry["high_conf_evidence"] += 1
    return summary


def _must_have_competency_ids(plan: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(str(item["competency_id"]) for item in plan if item.get("competency_id") and item.get("must_have")))


def _verification_uncertainty(item: dict[str, Any], summary: dict[str, dict[str, Any]], competency_id: str) -> float:
    """[0,1] how much we still do not know about this competency."""
    status = str(item.get("status") or "pending")
    attempts = int(item.get("attempt_count") or 0)
    if status == "disputed":
        return 0.8
    if status in {"in_progress", "partial"}:
        return 0.65
    if attempts == 0:
        return 0.85
    entry = summary.get(competency_id)
    if entry and entry["high_conf_evidence"] >= 2:
        return 0.3
    return 0.7


def _expected_information_gain(
    item: dict[str, Any],
    summary: dict[str, dict[str, Any]],
    competency_id: str,
    contradiction_topics: set[str],
    new_claim_topics: set[str],
) -> float:
    """[0,1] how much a question here is likely to change our belief."""
    if competency_id in contradiction_topics:
        return 0.95
    if competency_id in new_claim_topics:
        return 0.9
    entry = summary.get(competency_id)
    if entry is None or entry["high_conf_evidence"] == 0:
        return 0.85  # untested or no strong evidence yet
    if entry["high_conf_evidence"] >= 2:
        return 0.4
    return 0.6


def _resume_risk(item: dict[str, Any]) -> float:
    """[0,1] resume-claim risk.  Missing/unknown claims are the riskiest."""
    multiplier = float(item.get("risk_multiplier") or 1.4)
    return round(max(0.0, min(1.0, multiplier / 2.2)), 4)


def _repetition_penalty(item: dict[str, Any], recent_topics: list[str]) -> float:
    """[0,1] avoid re-asking the same topic or a heavily attempted item."""
    penalty = 0.4 if str(item.get("topic_id")) in recent_topics else 0.0
    penalty += min(int(item.get("attempt_count") or 0), 8) * 0.2
    return round(min(1.0, penalty), 4)


def _time_cost(item: dict[str, Any], current_difficulty: str) -> float:
    """[0,1] cost of asking now; coding and harder questions cost more time."""
    cost = {"beginner": 0.1, "medium": 0.2, "advanced": 0.3}.get(str(current_difficulty), 0.2)
    if str(item.get("preferred_question_type")) == "coding":
        cost += 0.15
    return round(min(1.0, cost + min(int(item.get("attempt_count") or 0), 4) * 0.05), 4)


def _comparability_penalty(item: dict[str, Any], unanchored_must_have: list[str], remaining_question_budget: int) -> float:
    """[0,1] penalize actions that would diverge from the anchor baseline.

    While a must-have competency has not yet been anchored, spending a question
    elsewhere weakens cross-interview comparability.  The penalty grows when the
    remaining budget is too small to both anchor and keep asking adaptively.
    """
    if not unanchored_must_have:
        return 0.0
    if str(item.get("competency_id")) in unanchored_must_have:
        return 0.0
    tightness = max(0.0, 1.0 - remaining_question_budget / max(len(unanchored_must_have), 1))
    return round(0.4 + 0.6 * tightness, 4)


def _action_factors(
    item: dict[str, Any],
    summary: dict[str, dict[str, Any]],
    contradiction_topics: set[str],
    new_claim_topics: set[str],
    recent_topics: list[str],
    unanchored_must_have: list[str],
    remaining_question_budget: int,
    current_difficulty: str,
) -> dict[str, Any]:
    """Deterministic planner v2 factor breakdown (see PLANNER_FACTOR_RANGES)."""
    competency_id = str(item.get("competency_id") or str(item.get("topic_id") or ""))
    jd_weight = max(0.0, min(1.0, float(item.get("jd_weight") or 0)))
    verification_uncertainty = _verification_uncertainty(item, summary, competency_id)
    expected_information_gain = _expected_information_gain(item, summary, competency_id, contradiction_topics, new_claim_topics)
    resume_risk = _resume_risk(item)
    repetition_penalty = _repetition_penalty(item, recent_topics)
    time_cost = _time_cost(item, current_difficulty)
    comparability_penalty = _comparability_penalty(item, unanchored_must_have, remaining_question_budget)
    action_value = round(
        jd_weight * verification_uncertainty * expected_information_gain * resume_risk
        - repetition_penalty
        - time_cost
        - comparability_penalty,
        6,
    )
    return {
        "requirement_id": str(item.get("requirement_id")),
        "topic_id": str(item.get("topic_id")),
        "competency_id": competency_id,
        "jd_weight": round(jd_weight, 6),
        "verification_uncertainty": round(verification_uncertainty, 4),
        "expected_information_gain": round(expected_information_gain, 4),
        "resume_risk": resume_risk,
        "repetition_penalty": repetition_penalty,
        "time_cost": time_cost,
        "comparability_penalty": comparability_penalty,
        "action_value": action_value,
    }


def _question_kind_for(
    item: dict[str, Any],
    summary: dict[str, dict[str, Any]],
    unanchored_must_have: list[str],
    action: str,
    competency_snapshot: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """(question_kind, anchor_group_id).

    The first question on an unanchored must-have competency is an anchor
    (stable baseline); coding questions keep their own kind; everything else is
    an adaptive follow-up / topic question. The anchor group id comes from the
    immutable competency snapshot, never from the mutable catalog.
    """
    competency_id = str(item.get("competency_id") or str(item.get("topic_id") or ""))
    if action == PlannerActionKind.ASK_CODING_QUESTION.value or str(item.get("preferred_question_type")) == "coding":
        return "coding", ""
    # A project candidate that wins the planner race must remain a project
    # question.  Turning it into a canonical anchor here would silently discard
    # the selected claim while leaving project ids in the planner action.
    if action == PlannerActionKind.VERIFY_PROJECT_CLAIM.value:
        return "adaptive", ""
    if competency_id in unanchored_must_have:
        anchor_group_id = ""
        if competency_snapshot:
            for group in (competency_snapshot.get("anchor_groups") or {}).values():
                if group.get("competency_id") == competency_id:
                    anchor_group_id = str(group.get("anchor_group_id") or "")
                    break
        return "anchor", anchor_group_id
    return "adaptive", ""


def _project_planner_candidates(
    candidate_state: dict[str, Any],
    unanchored_must_have: list[str],
    remaining_question_budget: int,
) -> list[dict[str, Any]]:
    """Deterministic live scoring of the frozen project attack-map targets.

    The frozen per-target ``priority`` is adjusted by the claim attempt count
    (a claim may be attacked at most PROJECT_CLAIM_MAX_FOLLOWUPS times across
    all its dimensions), by coverage (verified claim / covered JD requirement)
    and by the must-have anchor guard (while any must-have competency is still
    unanchored, project questions pay a comparability penalty so they never
    crowd out the fixed anchor baseline).
    """
    attack_map = candidate_state.get("project_attack_map") or []
    claim_state = candidate_state.get("project_claim_state") or {}
    covered = {str(item) for item in (candidate_state.get("covered_requirement_ids") or [])}
    comparability = 0.0
    if unanchored_must_have:
        tightness = max(0.0, 1.0 - remaining_question_budget / max(len(unanchored_must_have), 1))
        comparability = round(0.4 + 0.6 * tightness, 4)

    claim_attempts: dict[str, int] = {}
    verified_claims: set[str] = set()
    for target in attack_map:
        claim_key = f"{target.get('project_id') or ''!s}::{target.get('claim_id') or ''!s}"
        claim_attempts[claim_key] = 0
    for target_id, row in (claim_state or {}).items():
        for claim_key in claim_attempts:
            if target_id.startswith(claim_key + "::"):
                claim_attempts[claim_key] += int(row.get("attempt_count") or 0)
                if row.get("status") == ProjectClaimStatus.VERIFIED.value:
                    verified_claims.add(claim_key)

    result: list[dict[str, Any]] = []
    for target in attack_map:
        target_id = str(target.get("target_id") or "")
        target_status = str(target.get("status") or "pending")
        if target_status not in {"pending", "partial"}:
            continue
        # A target whose claim-specific evidence could not be retrieved is
        # skipped: a project question may never be generated without it, so
        # the planner degrades to a foundation question instead of failing.
        target_row = (claim_state or {}).get(target_id) or {}
        if str(target_row.get("evidence_status") or "") == "unavailable":
            continue
        project_id = str(target.get("project_id") or "")
        claim_id = str(target.get("claim_id") or "")
        claim_key = f"{project_id}::{claim_id}"
        attempts = claim_attempts.get(claim_key, 0)
        if attempts >= PROJECT_CLAIM_MAX_FOLLOWUPS:
            continue
        frozen = float(target.get("priority") or 0.0)
        repetition = round(min(attempts, 4) * 0.2, 4)
        covered_penalty = 0.3 if claim_key in verified_claims else 0.0
        req_id = str(target.get("jd_requirement_id") or "")
        if req_id and req_id in covered:
            covered_penalty += 0.2
        # The frozen priority already embeds the dimension time cost; the live
        # score only adjusts for attempt repetition, coverage and the anchor
        # guard so the frozen ordering stays authoritative.
        time_cost = _DIMENSION_TIME_COST.get(str(target.get("dimension") or ""), 0.2)
        result.append(
            {
                "candidate_kind": "project",
                "target_id": target_id,
                "project_id": project_id,
                "project_name": str(target.get("project_name") or ""),
                "claim_id": claim_id,
                "claim_text": str(target.get("claim_text") or "")[:500],
                "claim_type": str(target.get("claim_type") or "mechanism"),
                "dimension": str(target.get("dimension") or ""),
                "topic_id": str(target.get("topic_id") or ""),
                "requirement_id": str(target.get("jd_requirement_id") or ""),
                "priority": round(frozen, 6),
                "action_value": round(frozen - repetition - covered_penalty - comparability, 6),
                "repetition_penalty": repetition,
                "covered_penalty": round(covered_penalty, 4),
                "comparability_penalty": comparability,
                "time_cost": time_cost,
                "verification_uncertainty": round(max(0.0, min(1.0, 0.85 - attempts * 0.1)), 4),
                "expected_information_gain": 0.9 if attempts == 0 else 0.6,
                "jd_weight": round(max(0.0, min(1.0, frozen)), 4),
            }
        )
    result.sort(key=lambda row: (-row["action_value"], str(row["target_id"])))
    return result


def _project_question_mix(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the auditable project/foundation mix for non-anchor main questions."""
    project_questions = 0
    foundation_questions = 0
    for row in rounds:
        if str(row.get("question_kind") or "adaptive") == "anchor":
            continue
        actions = row.get("planner_actions") or []
        action = actions[0] if actions and isinstance(actions[0], dict) else {}
        if str(action.get("target_project_id") or ""):
            project_questions += 1
        else:
            foundation_questions += 1
    total = project_questions + foundation_questions
    return {
        "project_questions": project_questions,
        "foundation_questions": foundation_questions,
        "counted_questions": total,
        "project_share": round(project_questions / total, 4) if total else 0.0,
        "target_project_share": PROJECT_QUESTION_SHARE_TARGET,
    }


def _prefer_project_for_next_question(rounds: list[dict[str, Any]]) -> tuple[bool, dict[str, Any]]:
    """Choose the next side that keeps the deterministic mix closest to 70/30."""
    mix = _project_question_mix(rounds)
    total = int(mix["counted_questions"])
    project_questions = int(mix["project_questions"])
    project_error = abs((project_questions + 1) / (total + 1) - PROJECT_QUESTION_SHARE_TARGET)
    foundation_error = abs(project_questions / (total + 1) - PROJECT_QUESTION_SHARE_TARGET)
    prefer_project = project_error <= foundation_error
    return prefer_project, {
        **mix,
        "next_preference": "project" if prefer_project else "foundation",
        "project_next_error": round(project_error, 4),
        "foundation_next_error": round(foundation_error, 4),
    }


_DIMENSION_FOR_FACT_KIND: dict[str, str] = {
    "mechanism": "implementation",
    "decision": "selection",
    "tradeoff": "tradeoff",
    "failure_mode": "failure",
    "metric_definition": "metric",
}


def _round_project_target(round_data: dict[str, Any]) -> dict[str, Any] | None:
    """The (project, claim, dimension) the round's prompting action targeted."""
    actions = round_data.get("planner_actions") or []
    if not actions or not isinstance(actions[-1], dict):
        return None
    last = actions[-1]
    project_id = str(last.get("target_project_id") or "")
    claim_id = str(last.get("target_claim_id") or "")
    if not project_id or not claim_id:
        return None
    supporting = last.get("supporting_state") or {}
    return {
        "project_id": project_id,
        "claim_id": claim_id,
        "dimension": str(last.get("project_dimension") or ""),
        "followup_depth": int(last.get("project_followup_depth") or 0),
        "project_name": str(supporting.get("project_name") or ""),
        "claim_text": str(supporting.get("target_claim_fact") or "")[:500],
        "claim_type": str(supporting.get("claim_type") or ""),
        "topic_id": str(supporting.get("topic_id") or ""),
    }


def question_category_for_round(round_data: dict[str, Any]) -> dict[str, Any]:
    """Deterministically classify one round for the frontend.

    Returns ``{category, ...}`` where category is one of:
    ``project``  -- a claim-bound project deep-dive (project/claim/dimension all valid);
    ``foundation`` -- an adaptive JD/foundation question (may be pulled by a project's tech);
    ``anchor``  -- a fixed must-have anchor baseline;
    ``coding``  -- a coding question.

    A round is a *project* deep-dive ONLY when the prompting action carries a
    complete project binding; otherwise it must never be labelled as one.
    """
    actions = round_data.get("planner_actions") or []
    action = actions[-1] if actions and isinstance(actions[-1], dict) else {}
    question_kind = str(round_data.get("question_kind") or action.get("question_kind") or "adaptive")
    if str(round_data.get("question_type") or action.get("preferred_question_type") or "") == "coding":
        return {"category": "coding", "project_bound": False}
    if question_kind == "anchor":
        return {"category": "anchor", "project_bound": False}
    project_id = str(action.get("target_project_id") or "")
    claim_id = str(action.get("target_claim_id") or "")
    dimension = str(action.get("project_dimension") or "")
    project_bound = bool(project_id and claim_id and dimension)
    if project_bound:
        return {
            "category": "project",
            "project_bound": True,
            "project_id": project_id,
            "claim_id": claim_id,
            "dimension": dimension,
            "project_name": str((action.get("supporting_state") or {}).get("project_name") or ""),
            "claim_text": str((action.get("supporting_state") or {}).get("target_claim_fact") or "")[:500],
            "followup_depth": int(action.get("project_followup_depth") or 0),
        }
    pulled = (action.get("supporting_state") or {}).get("pulled_by_project") or round_data.get("pulled_by_project")
    return {
        "category": "foundation",
        "project_bound": False,
        "pulled_by_project": dict(pulled) if isinstance(pulled, dict) else None,
    }


def _claim_attempt_total(candidate_state: dict[str, Any], project_id: str, claim_id: str) -> int:
    claim_states = candidate_state.get("project_claim_state") or {}
    prefix = f"{project_id}::{claim_id}::"
    return sum(int((row or {}).get("attempt_count") or 0) for target_id, row in claim_states.items() if target_id.startswith(prefix))


def _project_followup_action(
    plan_item: dict[str, Any] | None,
    requirement_id: str | None,
    target_topic: str,
    competency_id: str,
    round_data: dict[str, Any],
    candidate_state: dict[str, Any],
    answer_state: dict[str, Any],
    followup_count: int,
    current_difficulty: str,
    judge: JudgeResult | None = None,
) -> PlannerAction | None:
    """Return a project deep-dive follow-up when the answer advanced a project claim.

    A follow-up is only issued for the round's OWN claim on the SAME dimension:
    ``project_facts`` attributed to a different claim never chain here, and the
    follow-up never crosses projects, never switches dimension and never exceeds
    the per-claim attempt cap (PROJECT_CLAIM_MAX_FOLLOWUPS).  The follow-up
    focus is chosen from the judge's claim-specific ``missing_points`` first
    (the highest-information gap on the current dimension); only when the judge
    produced none does it fall back to the newly attributed project fact.
    """
    current_target = _round_project_target(round_data)
    current_claim_id = str((current_target or {}).get("claim_id") or "")
    current_dimension = str((current_target or {}).get("dimension") or "")
    attributed = [
        item
        for item in answer_state.get("project_facts", [])
        if str(item.get("project_id") or "") and str(item.get("claim_id") or "")
    ]
    if current_claim_id:
        # Strict same-claim follow-up within the recorded target dimension: a
        # fact from a different claim never chains here.
        project_id = str((current_target or {}).get("project_id") or "")
        same_claim = [item for item in attributed if str(item.get("claim_id")) == current_claim_id and (not project_id or str(item.get("project_id")) == project_id)]
        target_fact = same_claim[0] if same_claim else None
        claim_id = current_claim_id
        dimension = current_dimension or _DIMENSION_FOR_FACT_KIND.get(str((target_fact or {}).get("fact_kind") or "mechanism"), "implementation")
        # A generic-but-correct answer often produces no project_fact at all.
        # It still deserves one focused project probe when the scorer reports
        # the claim as unverified/partial or exposes a claim-specific gap.
        incomplete_claim = judge is not None and (
            judge.claim_verification in {"unverified", "partial"}
            or judge.needs_followup
            or bool(judge.missing_points)
        )
        if target_fact is None and not incomplete_claim:
            return None
    else:
        # No recorded round target (legacy rounds / bare after-answer probes):
        # follow the most salient new project fact without crossing projects.
        if not attributed:
            return None
        target_fact = attributed[0]
        project_id = str(target_fact.get("project_id") or "")
        claim_id = str(target_fact.get("claim_id") or "")
        dimension = _DIMENSION_FOR_FACT_KIND.get(str(target_fact.get("fact_kind") or "mechanism"), "implementation")
    depth = int((current_target or {}).get("followup_depth") or 0) + 1
    # Main question is depth 0; depth 1 and 2 are the two allowed follow-ups.
    # Do not count the main answer as one of the follow-ups.
    if depth > PROJECT_CLAIM_MAX_FOLLOWUPS or followup_count >= PROJECT_CLAIM_MAX_FOLLOWUPS:
        return None
    fact_text = str((target_fact or {}).get("fact") or "")
    claim_text = str((current_target or {}).get("claim_text") or fact_text)
    # Pick the highest-information missing point on this dimension, mirroring the
    # "回答只有原理 -> 追问数据流/故障窗口" strategy instead of a generic probe.
    missing = [str(item) for item in (judge.missing_points if judge else []) if str(item).strip()]
    focus = ""
    dimension_terms = concept_terms(dimension)
    for point in missing:
        if concept_terms(point) & dimension_terms:
            focus = point
            break
    if not focus and missing:
        focus = missing[0]
    dimension_focus = {
        "implementation": "你在项目中的实际模块边界、数据流和亲自实现部分",
        "selection": "备选方案、选择依据以及没有采用其他方案的原因",
        "failure": "故障发生的具体窗口、状态变化和恢复过程",
        "tradeoff": "该设计在一致性、可用性、成本和复杂度之间的取舍",
        "data": "真实的数据结构、存储位置和状态变更",
        "interface": "上下游接口契约、错误边界和失败反馈",
        "metric": "优化前基线、控制变量、样本量和测量方法",
        "testing": "用于证明该机制有效的测试、日志或故障注入",
    }.get(dimension, f"{dimension} 维度的项目实现细节")
    followup_focus = focus or dimension_focus or fact_text
    return PlannerAction(
        PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value,
        requirement_id,
        target_topic,
        "项目回答仍未完整验证该声明的当前维度，需要在同一项目/声明/维度下继续深挖。",
        {
            "new_project_fact_count": len(attributed),
            "followup_count": followup_count,
            "target_claim_fact": claim_text,
            "target_project_id": project_id,
            "target_claim_id": claim_id,
            "project_name": str((current_target or {}).get("project_name") or ""),
            "claim_type": str((current_target or {}).get("claim_type") or ""),
            "topic_id": str((current_target or {}).get("topic_id") or ""),
        },
        followup_focus=followup_focus,
        target_difficulty=current_difficulty,
        preferred_question_type=str(round_data.get("question_type") or "scenario"),
        question_kind="adaptive",
        competency_id=competency_id,
        target_project_id=project_id,
        target_claim_id=claim_id,
        project_dimension=dimension,
        project_followup_depth=depth,
        action_factors={
            "reason_branch": "project_deep_dive",
            "verification_uncertainty": 0.85,
            "expected_information_gain": 0.9,
            "resume_risk": round(_resume_risk(dict(plan_item)) if plan_item else 0.5, 4),
        },
        decision_audit={
            "reason_branch": "project_deep_dive",
            "followup_budget": {"followup_count": followup_count},
            "target_contradiction_id": "",
            "target_claim_fact": claim_text,
            "target_project_id": project_id,
            "target_claim_id": claim_id,
            "project_dimension": dimension,
            "followup_source": "missing_point" if focus else "project_fact",
        },
    )


def downgrade_project_action(action: PlannerAction) -> PlannerAction:
    """Deterministically turn a project dive action into a marked foundation action.

    Used when no claim-relevant evidence can be retrieved for the project
    target: the same topic is still asked, but as an explicitly marked
    "foundation/bridge" question (question_kind="foundation") with all project
    binding removed, so it can never masquerade as a project deep-dive.
    """
    supporting_state = {
        key: value
        for key, value in (action.supporting_state or {}).items()
        if key not in {"target_claim_fact", "target_project_id", "target_claim_id", "project_dimension", "project_name", "claim_type"}
    }
    supporting_state["downgraded_from_project"] = True
    factors = dict(action.action_factors or {})
    factors["reason_branch"] = "project_evidence_downgraded"
    factors["downgraded_from_project"] = True
    return PlannerAction(
        PlannerActionKind.VERIFY_JD_REQUIREMENT.value,
        action.target_requirement_id,
        action.target_topic,
        "该项目声明的技术证据不可用，降级为同主题基础能力题（不伪装成项目深挖）。",
        supporting_state,
        target_difficulty=action.target_difficulty,
        preferred_question_type=action.preferred_question_type,
        question_kind="foundation",
        competency_id=action.competency_id,
        expected_evidence=dict(action.expected_evidence or {}),
        action_factors=factors,
        decision_audit={
            **dict(action.decision_audit or {}),
            "reason_branch": "project_evidence_downgraded",
            "downgraded_from_project": True,
            "target_project_id": str(action.target_project_id or ""),
            "target_claim_id": str(action.target_claim_id or ""),
            "project_dimension": str(action.project_dimension or ""),
        },
    )


def choose_planner_action(
    plan: list[dict[str, Any]],
    candidate_state: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    remaining_question_budget: int,
    current_difficulty: str,
    competency_snapshot: dict[str, Any] | None = None,
) -> PlannerAction:
    input_hashes = _planner_input_hashes(plan, candidate_state, rounds, competency_snapshot)
    if remaining_question_budget <= 0:
        return PlannerAction(
            PlannerActionKind.FINISH_INTERVIEW.value,
            None,
            None,
            "题目预算已用尽。",
            {"remaining_question_budget": 0},
            target_difficulty=current_difficulty,
            decision_audit={"reason_branch": "budget_exhausted", "budget": {"remaining_question_budget": 0}, "input": input_hashes},
        )
    pre_guard_eligible = [item for item in plan if item.get("status") in {"pending", "in_progress", "partial", "disputed"}]
    eligible = pre_guard_eligible
    terminal_items = [item for item in plan if item.get("status") not in {"pending", "in_progress", "partial", "disputed"}]
    recent_topics = [str(row.get("topic")) for row in rounds[-2:]]
    new_claim_topics = {str(topic) for fact in candidate_state.get("newly_claimed_facts", []) for topic in fact.get("topic_ids", [])}
    contradiction_topics = {str(topic) for contradiction in candidate_state.get("contradictions", []) if contradiction.get("status") == "unresolved" for topic in contradiction.get("topic_ids", [])}
    summary = _evidence_summary(rounds, competency_snapshot)
    must_have = _must_have_competency_ids(eligible)
    unanchored_must_have = [cid for cid in must_have if not summary.get(cid, {}).get("anchor_done")]

    unattempted = [item for item in eligible if item.get("status") == "pending" and int(item.get("attempt_count") or 0) == 0]
    unanchored_items = [item for item in eligible if str(item.get("competency_id")) in unanchored_must_have]
    # Preserve capacity for both never-tested requirements and must-have
    # competencies whose anchor baseline is still missing.  An unanchored
    # must-have may never be silently skipped just because it looks low-risk.
    protected = unattempted + [item for item in unanchored_items if item not in unattempted]
    guard_active = bool(protected and remaining_question_budget <= len(protected))
    if guard_active:
        eligible = protected

    # Foundation questions should be naturally pulled by the technology the
    # most recent project dive used, so we never land several consecutive
    # detached 八股 questions after a project round.
    last_project_topic = ""
    last_project_name = ""
    for row in reversed(rounds):
        actions = row.get("planner_actions") or []
        for action in reversed(actions):
            if isinstance(action, dict) and (action.get("target_project_id") or ""):
                last_project_topic = str(action.get("target_topic") or "")
                last_project_name = str((action.get("supporting_state") or {}).get("project_name") or "")
                break
        if last_project_topic:
            break
    candidates = [
        {**_action_factors(
            item,
            summary,
            contradiction_topics,
            new_claim_topics,
            recent_topics,
            unanchored_must_have,
            remaining_question_budget,
            current_difficulty,
        ), "candidate_kind": "jd"}
        for item in eligible
    ]
    for row in candidates:
        topic_pull = 0.12 if last_project_topic and row.get("topic_id") == last_project_topic else 0.0
        row["topic_pull_bonus"] = topic_pull
        row["action_value"] = round(row["action_value"] + topic_pull, 6)
    candidates.sort(key=lambda row: (-row["action_value"], str(row.get("requirement_id") or "")))
    # Project attack-map candidates compete with the JD candidates.  The old
    # hard rule (no project question before every must-have anchor is complete)
    # is removed: a high-priority, JD-matched project claim may lead, and the
    # 70/30 project/foundation quota keeps anchors and foundation questions in
    # the mix.  Only the budget guard (remaining questions == exactly the
    # protected/unattempted items) still keeps project questions out so a
    # must-have anchor is never dropped by budget exhaustion.  Targets whose
    # claim-specific evidence could not be retrieved are skipped here (they
    # degrade to foundation questions downstream).
    project_candidates = _project_planner_candidates(candidate_state, unanchored_must_have, remaining_question_budget)
    if guard_active:
        project_candidates = []
    prefer_project, question_mix = _prefer_project_for_next_question(rounds)
    quota_applied = bool(candidates and project_candidates)
    if quota_applied:
        combined = project_candidates if prefer_project else candidates
    else:
        combined = [*candidates, *project_candidates]
    combined.sort(key=lambda row: (-row["action_value"], str(row.get("requirement_id") or ""), str(row.get("target_id") or "")))
    if not combined:
        return PlannerAction(
            PlannerActionKind.FINISH_INTERVIEW.value,
            None,
            None,
            "所有可映射的 JD 要求与项目声明均已覆盖。",
            {"remaining_question_budget": remaining_question_budget},
            target_difficulty=current_difficulty,
            decision_audit={
                "reason_branch": "no_eligible",
                "budget": {"remaining_question_budget": remaining_question_budget},
                "input": input_hashes,
            },
        )
    best = combined[0]
    is_project_target = best.get("candidate_kind") == "project"
    if is_project_target:
        selected = best
        target_requirement_id = str(best.get("requirement_id") or "") or None
        selected_topic = str(best.get("topic_id") or "")
        preferred_type = "scenario"
        strategy = PlannerActionKind.VERIFY_PROJECT_CLAIM.value
    else:
        selected = next((item for item in eligible if item.get("requirement_id") == best.get("requirement_id")), eligible[0])
        target_requirement_id = str(selected.get("requirement_id"))
        preferred_type = str(selected.get("preferred_question_type") or "scenario")
        strategy = str(selected.get("verification_strategy") or PlannerActionKind.VERIFY_JD_REQUIREMENT.value)
        selected_topic = str(selected.get("topic_id"))
    if selected_topic in contradiction_topics:
        action = PlannerActionKind.RESOLVE_CONTRADICTION.value
    elif is_project_target:
        action = PlannerActionKind.VERIFY_PROJECT_CLAIM.value
    elif preferred_type == "coding":
        action = PlannerActionKind.ASK_CODING_QUESTION.value
    elif rounds and selected_topic != str(rounds[-1].get("topic")):
        action = PlannerActionKind.SWITCH_TOPIC.value
    else:
        action = strategy
    question_kind, anchor_group_id = _question_kind_for(selected, summary, unanchored_must_have, action, competency_snapshot)
    factors = best
    best_value = float(best.get("action_value") or 0.0)
    # Stop early only when nothing important is left: an untested requirement or
    # an unanchored must-have competency always earns its reserved question even
    # if its estimated information gain is small.
    if best_value < PLANNER_FINISH_THRESHOLD and not protected and not unanchored_must_have and not is_project_target and not quota_applied:
        # Every remaining question is expected to add little information and
        # the anchor baseline is complete: stop instead of burning budget.
        return PlannerAction(
            PlannerActionKind.FINISH_INTERVIEW.value,
            None,
            None,
            "剩余问题的预计信息增益低于阈值。",
            {"remaining_question_budget": remaining_question_budget, "best_action_value": best_value},
            target_difficulty=current_difficulty,
            decision_audit={
                "reason_branch": "low_info_gain",
                "budget": {"remaining_question_budget": remaining_question_budget, "best_action_value": best_value},
                "input": input_hashes,
            },
        )
    if is_project_target:
        project_name = str(best.get("project_name") or "")
        claim_text = str(best.get("claim_text") or "")
        dimension = str(best.get("dimension") or "")
        reasons = [f"项目声明验真：{project_name} — {claim_text}（{dimension} 维度）"]
    else:
        reasons = [str(selected.get("objective") or "验证 JD 要求")]
    if selected_topic in contradiction_topics:
        reasons.append("该主题存在尚未解决的回答矛盾")
    elif not is_project_target and str(selected.get("topic_id")) in new_claim_topics:
        reasons.append("候选人刚补充了相关新声明，需要验证")
    competency_id = str(selected.get("competency_id") or selected_topic)
    expected_evidence = {}
    resolved_target_difficulty = current_difficulty
    if competency_snapshot:
        rubrics = competency_snapshot.get("rubrics") or {}
        rubric = rubrics.get(competency_id) or {}
        expected_evidence = {
            "competency_id": competency_id,
            "rubric_version": rubric.get("rubric_version") or competency_snapshot.get("rubric_version") or "",
            "target_level": int(rubric.get("required_score") or 3),
            "profile_level": rubric.get("target_level") or competency_snapshot.get("level") or "mid",
            "level_expectation": rubric.get("level_expectation") or "",
            "target_indicators": list(rubric.get("observable_indicators") or []),
            "allowed_evidence_types": list(rubric.get("allowed_evidence_types") or []),
            "anchor_behavior": {
                level: (rubric.get("score_anchors") or {}).get(level, {}).get("observable_behavior")
                for level in ("2", "3", "4")
            },
        }
        if anchor_group_id:
            anchor_group = ((competency_snapshot.get("anchor_groups") or {}).get(anchor_group_id) or {})
            resolved_target_difficulty = str(anchor_group.get("difficulty") or current_difficulty)
            expected_evidence.update(
                {
                    "anchor_question_ids": list(anchor_group.get("question_ids") or []),
                    "anchor_content_type": anchor_group.get("content_type") or "",
                    "anchor_difficulty": anchor_group.get("difficulty") or current_difficulty,
                }
            )
    supporting_state = {
        "remaining_question_budget": remaining_question_budget,
        "covered_requirement_ids": list(candidate_state.get("covered_requirement_ids") or []),
        "new_claim_topics": sorted(new_claim_topics),
        "contradiction_topics": sorted(contradiction_topics),
        "recent_topics": recent_topics,
        "unanchored_must_have": unanchored_must_have,
    }
    if not is_project_target and last_project_topic and selected_topic == last_project_topic:
        # A foundation question naturally pulled by the technology the most
        # recent project dive used: surface the source so the UI can explain it.
        supporting_state["pulled_by_project"] = {
            "topic_id": last_project_topic,
            "project_name": last_project_name,
        }
    target_project_id = ""
    target_claim_id = ""
    project_dimension = ""
    if is_project_target:
        target_project_id = str(best.get("project_id") or "")
        target_claim_id = str(best.get("claim_id") or "")
        project_dimension = str(best.get("dimension") or "")
        supporting_state.update(
            {
                "target_claim_fact": str(best.get("claim_text") or ""),
                "target_project_id": target_project_id,
                "target_claim_id": target_claim_id,
                "project_dimension": project_dimension,
                "project_name": str(best.get("project_name") or ""),
                "claim_type": str(best.get("claim_type") or ""),
                "topic_id": str(best.get("topic_id") or ""),
            }
        )
    return PlannerAction(
        action,
        target_requirement_id,
        selected_topic,
        "；".join(reasons)[:1000],
        supporting_state,
        # Adaptive questions follow session difficulty; canonical anchors keep
        # the reviewed difficulty frozen with their group.
        target_difficulty=resolved_target_difficulty,
        preferred_question_type=preferred_type,
        question_kind=question_kind,
        competency_id=competency_id,
        anchor_group_id=anchor_group_id,
        expected_evidence=expected_evidence,
        action_factors=factors or {},
        target_project_id=target_project_id,
        target_claim_id=target_claim_id,
        project_dimension=project_dimension,
        decision_audit={
            "reason_branch": "planner",
            "candidates": candidates,
            "project_candidates": project_candidates,
            "eliminated": [
                {"requirement_id": str(item.get("requirement_id")), "topic_id": str(item.get("topic_id")), "reason": "verified_or_terminal_status"}
                for item in terminal_items
            ]
            + (
                [
                    {
                        "requirement_id": str(item.get("requirement_id")),
                        "topic_id": str(item.get("topic_id")),
                        "reason": "unattempted_guard",
                    }
                    for item in pre_guard_eligible
                    if item not in protected
                ]
                if guard_active
                else []
            )
            + [
                {
                    "target_id": str(target.get("target_id") or ""),
                    "project_id": str(target.get("project_id") or ""),
                    "claim_id": str(target.get("claim_id") or ""),
                    "reason": "project_evidence_unavailable",
                }
                for target in (candidate_state.get("project_attack_map") or [])
                if str(((candidate_state.get("project_claim_state") or {}).get(str(target.get("target_id") or "")) or {}).get("evidence_status") or "") == "unavailable"
            ],
            "selected": {
                "requirement_id": target_requirement_id,
                "topic_id": selected_topic,
                "competency_id": competency_id,
                "action": action,
                "question_kind": question_kind,
                "candidate_kind": "project" if is_project_target else "jd",
                "target_project_id": target_project_id,
                "target_claim_id": target_claim_id,
                "project_dimension": project_dimension,
                "reason": "；".join(reasons)[:1000],
            },
            "budget": {
                "remaining_question_budget": remaining_question_budget,
                "protected_guard": guard_active,
                "contradiction_guard": guard_active,
                "question_mix": question_mix,
            },
            "input": input_hashes,
        },
    )


def choose_after_answer_action(
    plan: list[dict[str, Any]],
    candidate_state: dict[str, Any],
    answer_state: dict[str, Any],
    judge: JudgeResult,
    round_data: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    remaining_question_budget: int,
    max_followups: int,
    current_difficulty: str,
    competency_snapshot: dict[str, Any] | None = None,
) -> PlannerAction:
    followup_count = int(round_data.get("followup_count") or 0)
    target_topic = str(round_data.get("topic") or "")
    requirement_id = str(round_data.get("target_requirement_id") or "") or None
    competency_id = str(round_data.get("competency_id") or target_topic)
    plan_item = next((item for item in plan if item.get("requirement_id") == requirement_id), None)
    current_project_target = _round_project_target(round_data) or {}
    if followup_count < max_followups:
        contradictions = [item for item in answer_state.get("contradictions", []) if not item.get("topic_ids") or target_topic in item.get("topic_ids", [])]
        if contradictions:
            contradiction = contradictions[0]
            contradiction_id = str(contradiction.get("contradiction_id") or "")
            return PlannerAction(
                PlannerActionKind.RESOLVE_CONTRADICTION.value,
                requirement_id,
                target_topic,
                "回答与已有声明出现可审计矛盾，优先澄清。",
                {
                    "contradiction_count": len(contradictions),
                    "followup_count": followup_count,
                    "target_contradiction_id": contradiction_id,
                    "target_project_id": str(current_project_target.get("project_id") or ""),
                    "target_claim_id": str(current_project_target.get("claim_id") or ""),
                    "project_dimension": str(current_project_target.get("dimension") or ""),
                    "project_name": str(current_project_target.get("project_name") or ""),
                    "claim_type": str(current_project_target.get("claim_type") or ""),
                },
                followup_focus=f"请澄清“{contradiction.get('statement')}”与“{contradiction.get('conflicts_with')}”之间的差异",
                target_contradiction_id=contradiction_id,
                target_difficulty=current_difficulty,
                preferred_question_type=str(round_data.get("question_type") or "scenario"),
                question_kind="adaptive",
                competency_id=competency_id,
                target_project_id=str(current_project_target.get("project_id") or ""),
                target_claim_id=str(current_project_target.get("claim_id") or ""),
                project_dimension=str(current_project_target.get("dimension") or ""),
                project_followup_depth=int(current_project_target.get("followup_depth") or 0) + (1 if current_project_target else 0),
                action_factors={
                    "reason_branch": "contradiction",
                    "verification_uncertainty": 1.0,
                    "expected_information_gain": 0.95,
                    "resume_risk": round(_resume_risk(dict(plan_item)) if plan_item else 0.5, 4),
                },
                decision_audit={
                    "reason_branch": "contradiction",
                    "followup_budget": {"followup_count": followup_count, "max_followups": max_followups},
                    "target_contradiction_id": contradiction_id,
                    "target_claim_fact": "",
                    "target_project_id": str(current_project_target.get("project_id") or ""),
                    "target_claim_id": str(current_project_target.get("claim_id") or ""),
                    "project_dimension": str(current_project_target.get("dimension") or ""),
                },
            )
        project_followup = _project_followup_action(
            plan_item,
            requirement_id,
            target_topic,
            competency_id,
            round_data,
            candidate_state,
            answer_state,
            followup_count,
            current_difficulty,
            judge=judge,
        )
        if project_followup is not None:
            return project_followup
        new_claims = [item for item in answer_state.get("newly_claimed_facts", []) if target_topic in item.get("topic_ids", [])]
        if new_claims:
            target_claim = str(new_claims[0].get("fact") or "")
            return PlannerAction(
                PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value,
                requirement_id,
                target_topic,
                "回答产生了与当前 JD 主题相关的新能力声明，需要独立验证。",
                {
                    "new_claim_count": len(new_claims),
                    "followup_count": followup_count,
                    "target_claim_fact": target_claim,
                },
                followup_focus=target_claim or "新能力声明",
                target_difficulty=current_difficulty,
                preferred_question_type=str(round_data.get("question_type") or "scenario"),
                question_kind="adaptive",
                competency_id=competency_id,
                action_factors={
                    "reason_branch": "new_claim",
                    "verification_uncertainty": 0.85,
                    "expected_information_gain": 0.9,
                },
                decision_audit={
                    "reason_branch": "new_claim",
                    "followup_budget": {"followup_count": followup_count, "max_followups": max_followups},
                    "target_contradiction_id": "",
                    "target_claim_fact": target_claim,
                },
            )
        if judge.needs_followup:
            return PlannerAction(
                PlannerActionKind.FOLLOW_UP_CURRENT_CLAIM.value,
                requirement_id,
                target_topic,
                "当前回答仍有与评分标准相关的未验证边界。",
                {"missing_points": len(judge.missing_points), "followup_count": followup_count},
                followup_focus=judge.followup_focus,
                target_difficulty=current_difficulty,
                preferred_question_type=str(round_data.get("question_type") or "scenario"),
                question_kind="adaptive",
                competency_id=competency_id,
                action_factors={
                    "reason_branch": "judge_needs_followup",
                    "verification_uncertainty": 0.7,
                    "expected_information_gain": 0.75,
                    "missing_points": len(judge.missing_points),
                },
                decision_audit={
                    "reason_branch": "judge_needs_followup",
                    "followup_budget": {"followup_count": followup_count, "max_followups": max_followups},
                    "target_contradiction_id": "",
                    "target_claim_fact": "",
                },
            )
    return choose_planner_action(
        plan,
        candidate_state,
        rounds,
        remaining_question_budget=remaining_question_budget,
        current_difficulty=current_difficulty,
        competency_snapshot=competency_snapshot,
    )


SUPPORTED_PLANNER_VERSIONS = frozenset({PLANNER_VERSION})


def choose_planner_action_versioned(
    planner_version: str,
    plan: list[dict[str, Any]],
    candidate_state: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    remaining_question_budget: int,
    current_difficulty: str,
    competency_snapshot: dict[str, Any] | None = None,
) -> PlannerAction:
    """Dispatch through the explicit planner registry.

    Experiments may only bind implementations present in this registry. This
    prevents a session from advertising a planner version while silently
    executing another one.
    """
    if planner_version not in SUPPORTED_PLANNER_VERSIONS:
        raise DomainError("unsupported_planner_version", f"Planner version {planner_version} is not executable.")
    return choose_planner_action(
        plan,
        candidate_state,
        rounds,
        remaining_question_budget=remaining_question_budget,
        current_difficulty=current_difficulty,
        competency_snapshot=competency_snapshot,
    )


def choose_after_answer_action_versioned(
    planner_version: str,
    plan: list[dict[str, Any]],
    candidate_state: dict[str, Any],
    answer_state: dict[str, Any],
    judge: JudgeResult,
    round_data: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    remaining_question_budget: int,
    max_followups: int,
    current_difficulty: str,
    competency_snapshot: dict[str, Any] | None = None,
) -> PlannerAction:
    if planner_version not in SUPPORTED_PLANNER_VERSIONS:
        raise DomainError("unsupported_planner_version", f"Planner version {planner_version} is not executable.")
    return choose_after_answer_action(
        plan,
        candidate_state,
        answer_state,
        judge,
        round_data,
        rounds,
        remaining_question_budget=remaining_question_budget,
        max_followups=max_followups,
        current_difficulty=current_difficulty,
        competency_snapshot=competency_snapshot,
    )


@dataclass(frozen=True)
class PolicyDecision:
    topic_id: str
    topic_name: str
    category: str
    question_type: str
    difficulty: str
    supports_code: bool
    fallback_categories: tuple[str, ...]


REQUIRED_METADATA = {
    "content_type",
    "role",
    "topic",
    "difficulty",
    "question_id",
    "source",
    "source_date",
    "quality_score",
    "verified",
    "license",
}

CONTENT_TYPES = {"interview_experience", "leetcode", "fundamentals"}
CONTENT_TYPE_FOR_CATEGORY = {
    "interview_experience": "interview_experience",
    "leetcode": "leetcode",
    "baguwen": "fundamentals",
}


def validate_metadata(metadata: dict[str, Any], *, expected_content_type: str | None = None) -> list[str]:
    errors = [f"missing:{name}" for name in sorted(REQUIRED_METADATA - set(metadata))]
    content_type = metadata.get("content_type")
    if content_type is not None and content_type not in CONTENT_TYPES:
        errors.append("invalid:content_type")
    if expected_content_type and content_type != expected_content_type:
        errors.append("mismatch:content_type")
    if metadata.get("difficulty") not in {item.value for item in Difficulty}:
        errors.append("invalid:difficulty")
    try:
        quality = float(metadata.get("quality_score"))
        if not 0 <= quality <= 1:
            errors.append("invalid:quality_score")
    except (TypeError, ValueError):
        errors.append("invalid:quality_score")
    if metadata.get("verified") is not True:
        errors.append("unverified")
    source_date = metadata.get("source_date")
    try:
        date.fromisoformat(str(source_date))
    except ValueError:
        errors.append("invalid:source_date")
    if not str(metadata.get("license", "")).strip():
        errors.append("invalid:license")
    return sorted(set(errors))


def metadata_quality(rows: Iterable[dict[str, Any]], expected_content_type: str) -> dict[str, Any]:
    rows = list(rows)
    details = []
    valid = 0
    for row in rows:
        errors = validate_metadata(row, expected_content_type=expected_content_type)
        details.append({"question_id": row.get("question_id"), "errors": errors})
        valid += not errors
    ratio = valid / len(rows) if rows else 0.0
    return {
        "document_count": len(rows),
        "valid_metadata_count": valid,
        "quality_ratio": round(ratio, 4),
        "ready": bool(rows) and ratio >= 0.95,
        "issues": [detail for detail in details if detail["errors"]][:20],
    }


_INJECTION_PATTERNS = re.compile(r"(?i)(ignore\s+(all\s+)?(previous|prior|system)|system\s+prompt|developer\s+message|改变.{0,8}(规则|指令)|忽略.{0,8}(指令|规则))")


def mark_untrusted(text: str, *, limit: int = 12_000) -> str:
    value = str(text)[:limit]
    value = _INJECTION_PATTERNS.sub("[untrusted-instruction-removed]", value)
    return f"<untrusted_data>\n{value}\n</untrusted_data>"


def validate_answer(answer: Any) -> str:
    if not isinstance(answer, str):
        raise DomainError("invalid_answer", "Answer must be text.")
    answer = answer.strip()
    if not answer:
        raise DomainError("invalid_answer", "Answer cannot be empty.")
    if len(answer) > MAX_ANSWER_CHARS:
        raise DomainError("answer_too_long", f"Answer cannot exceed {MAX_ANSWER_CHARS} characters.")
    return answer


def validate_code_request(language: Any, source_code: Any, tests: Any | None = None) -> tuple[str, str, list[dict[str, Any]]]:
    language = str(language).lower().strip()
    if language not in SUPPORTED_LANGUAGES:
        raise DomainError("unsupported_language", f"Supported languages: {', '.join(sorted(SUPPORTED_LANGUAGES))}.")
    if not isinstance(source_code, str) or not source_code.strip():
        raise DomainError("invalid_source", "Source code cannot be empty.")
    if len(source_code) > MAX_SOURCE_CHARS:
        raise DomainError("source_too_long", f"Source code cannot exceed {MAX_SOURCE_CHARS} characters.")
    if tests is None:
        tests = []
    if not isinstance(tests, list) or len(tests) > 50:
        raise DomainError("invalid_tests", "Tests must be a list with at most 50 cases.")
    normalized = []
    for case in tests:
        if not isinstance(case, dict) or "input" not in case or "expected" not in case:
            raise DomainError("invalid_tests", "Each test requires input and expected fields.")
        normalized.append({"input": case["input"], "expected": case["expected"]})
    return language, source_code, normalized


def payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lexical_similarity(left: str, right: str) -> float:
    tokens_left = set(re.findall(r"[\w\u4e00-\u9fff]+", left.lower()))
    tokens_right = set(re.findall(r"[\w\u4e00-\u9fff]+", right.lower()))
    if not tokens_left or not tokens_right:
        return 0.0
    return len(tokens_left & tokens_right) / len(tokens_left | tokens_right)


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def build_skill_verification(claimed_skills: list[dict[str, Any]], rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare resume-claimed skills against actual scores on related rounds.

    A claimed skill is "tested" when a completed round's topic is one of the
    claim's mapped topics, or the round's resume_probe names that skill.
    Pure function; deterministic and unit-testable.
    """
    completed = [row for row in rounds if row.get("status") == RoundStatus.COMPLETED.value and row.get("score") is not None]
    verification: list[dict[str, Any]] = []
    for claim in claimed_skills:
        skill = str(claim.get("skill") or "").strip()
        if not skill:
            continue
        topics = {str(topic) for topic in (claim.get("topics") or [])}
        skill_names = {skill.lower()}
        tested = [row for row in completed if str(row.get("topic", "")) in topics or any(str(name).lower() in skill_names for name in (row.get("resume_probe") or {}).get("skills", []))]
        scores = [float(row["score"]) for row in tested]
        average = _average(scores)
        count = len(scores)
        if count == 0:
            status = "not_tested"
            recommendation = "本场未覆盖，可在下一场加入 focus_topics 重点考察。"
        elif average >= 3:
            status = "verified"
            recommendation = "已实测通过，保持。"
        elif average >= 2:
            status = "partial"
            recommendation = f"声称 {claim.get('claimed_level', '')}，相关题目 {average:.1f}/4，建议围绕 {', '.join(sorted(topics))} 做专项复盘。"
        else:
            status = "disputed"
            recommendation = f"声称 {claim.get('claimed_level', '')}，相关题目仅 {average:.1f}/4，与简历描述存在差距，建议重点补强。"
        verification.append(
            {
                "skill": skill,
                "claimed_level": str(claim.get("claimed_level") or "familiar"),
                "topics": sorted(topics),
                "tested_round_count": count,
                "avg_score": average if count else None,
                "status": status,
                "recommendation": recommendation,
            }
        )
    return verification


def build_jd_verification_matrix(
    job_snapshot: dict[str, Any],
    match_snapshot: list[dict[str, Any]],
    rounds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute requirement verification only from persisted matches and completed rounds."""

    matches = {str(item.get("requirement_id")): item for item in match_snapshot}
    completed = [row for row in rounds if row.get("status") == RoundStatus.COMPLETED.value and row.get("score") is not None]
    matrix = []
    for requirement in (job_snapshot.get("extraction") or job_snapshot).get("requirements", []):
        requirement_id = str(requirement.get("requirement_id") or "")
        match = matches.get(requirement_id, {})
        tested = [row for row in completed if str(row.get("target_requirement_id") or "") == requirement_id]
        scores = [float(row["score"]) for row in tested]
        average = _average(scores) if scores else None
        if not tested:
            verification_status = VerificationStatus.UNTESTED.value
            recommendation = "本场未覆盖；下一场应优先验证该 JD 要求。"
        elif average is not None and average >= 3:
            verification_status = VerificationStatus.VERIFIED.value
            recommendation = "面试证据支持该要求，继续用真实项目复盘保持熟练度。"
        elif average is not None and average >= 2:
            verification_status = VerificationStatus.PARTIAL.value
            recommendation = "仅部分达到要求，应围绕遗漏边界进行专项练习和复测。"
        else:
            verification_status = VerificationStatus.DISPUTED.value
            recommendation = "面试结果与声明或岗位要求存在明显差距，应先补齐基础再复测。"
        support_evidence = []
        for row in tested:
            versions = list(row.get("evidence_versions") or [])
            if not versions:
                versions = [
                    {
                        "evidence_id": item.get("evidence_id"),
                        "dataset_id": item.get("dataset_id"),
                        "document_id": item.get("document_id"),
                        "source_date": item.get("metadata", {}).get("source_date"),
                        "content_sha256": item.get("metadata", {}).get("content_sha256"),
                    }
                    for item in row.get("retrieval_evidence", [])
                    if item.get("evidence_id")
                ]
            support_evidence.append(
                {
                    "round_id": row.get("id"),
                    "question_id": row.get("question_id"),
                    "evidence_ids": [item.get("evidence_id") for item in versions if item.get("evidence_id")],
                    "evidence_versions": versions,
                    "score": row.get("score"),
                }
            )
        matrix.append(
            {
                "requirement_id": requirement_id,
                "requirement_text": str(requirement.get("text") or ""),
                "category": str(requirement.get("category") or ""),
                "weight": float(requirement.get("weight") or 0),
                "resume_claim_status": str(match.get("match_status") or MatchStatus.UNKNOWN.value),
                "resume_evidence": list(match.get("resume_evidence") or []),
                "actual_questions": [
                    {
                        "round_id": row.get("id"),
                        "question_id": row.get("question_id"),
                        "question_text": row.get("question_text"),
                        "topic": row.get("topic"),
                    }
                    for row in tested
                ],
                "score": average,
                "verification_status": verification_status,
                "support_evidence": support_evidence,
                "improvement_recommendation": recommendation,
                "unmapped": bool(requirement.get("unmapped")),
            }
        )
    return matrix


def _round_low_confidence(row: dict[str, Any]) -> bool:
    evaluations = (row.get("evidence_evaluation") or {}).get("evaluations") or []
    return any(bool((item.get("evaluation") or {}).get("low_confidence")) for item in evaluations)


def _round_evidence_spans(row: dict[str, Any]) -> list[dict[str, Any]]:
    """Answer evidence spans for a round, from the stored 3-stage evaluation."""
    evaluations = (row.get("evidence_evaluation") or {}).get("evaluations") or []
    spans: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in evaluations:
        evaluation = item.get("evaluation") or {}
        for span_id in (evaluation.get("scorer") or {}).get("evidence_span_ids", []):
            if span_id in seen:
                continue
            seen.add(span_id)
            for span in (evaluation.get("extraction") or {}).get("answer_spans", []):
                if str(span.get("span_id")) == span_id:
                    spans.append({"span_id": span_id, "text": span.get("text")})
    return spans


def _competency_contradicted(competency_id: str, candidate_state: dict[str, Any] | None, rounds: list[dict[str, Any]]) -> bool:
    contradictions = (candidate_state or {}).get("contradictions") or []
    if any(contradiction.get("status") == "unresolved" and competency_id in (contradiction.get("topic_ids") or []) for contradiction in contradictions):
        return True
    for row in rounds:
        evaluations = (row.get("evidence_evaluation") or {}).get("evaluations") or []
        for item in evaluations:
            extraction = (item.get("evaluation") or {}).get("extraction") or {}
            if extraction.get("contradictions"):
                return True
    return False


def build_competency_verification(
    competency_snapshot: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    job_snapshot: dict[str, Any] | None = None,
    match_snapshot: list[dict[str, Any]] | None = None,
    candidate_state: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Per-competency evidence track and conclusion.

    Status vocabulary: verified / partial / insufficient_evidence / contradiction
    / uncovered. An uncovered competency carries no score (it is NOT a low
    score); a low-confidence result is never presented as a definitive score.
    """
    competencies = competency_snapshot.get("competencies") or []
    matches = {str(item.get("requirement_id")): item for item in match_snapshot or []}
    verification: list[dict[str, Any]] = []
    for competency in competencies:
        competency_id = str(competency.get("competency_id"))
        required_score = _required_score_for(competency_snapshot, competency_id)
        tested = [
            row
            for row in rounds
            if row.get("status") == RoundStatus.COMPLETED.value
            and row.get("score") is not None
            and (str(row.get("competency_id") or "") == competency_id or str(row.get("topic") or "") == competency_id)
        ]
        scores = [float(row["score"]) for row in tested]
        best_score = max(scores) if scores else None
        best_row = max(tested, key=lambda row: float(row["score"])) if tested else None
        contradictions = _competency_contradicted(competency_id, candidate_state, tested)
        low_confidence = bool(best_row and _round_low_confidence(best_row))
        anchor_done = any(
            row.get("question_kind") == "anchor"
            and float(row["score"]) >= required_score
            and float(row.get("judge_confidence") or 0) >= ANCHOR_CONFIDENCE_THRESHOLD
            and not _round_low_confidence(row)
            for row in tested
        )
        if not tested:
            status = "uncovered"
            conclusion = "本场未覆盖该能力；不构成能力结论，也不计低分。"
        elif contradictions:
            status = "contradiction"
            conclusion = "该能力下存在未解决的回答矛盾，结论待澄清后复核。"
        elif best_row and (low_confidence or best_score < 2):
            status = "insufficient_evidence"
            conclusion = "现有证据不足以对能力作出确定结论，不判低分。"
        elif best_score >= required_score and anchor_done:
            status = "verified"
            conclusion = f"锚点题与后续证据达到当前职级标准（{required_score}+ 分，高置信）。"
        elif best_score >= 2:
            status = "partial"
            conclusion = "证据显示部分达标，仍有边界或权衡未覆盖。"
        else:
            status = "insufficient_evidence"
            conclusion = "现有证据不足以对能力作出确定结论，不判低分。"
        evidence_track: list[dict[str, Any]] = []
        requirement_ids: list[str] = []
        for row in tested:
            requirement_id = str(row.get("target_requirement_id") or "")
            if requirement_id and requirement_id not in requirement_ids:
                requirement_ids.append(requirement_id)
            target_requirement = row.get("target_requirement") if isinstance(row.get("target_requirement"), dict) else {}
            if target_requirement.get("text"):
                evidence_track.append({"kind": "jd_requirement", "text": str(target_requirement.get("text"))[:300]})
            if requirement_id:
                resume_evidence = (matches.get(requirement_id) or {}).get("resume_evidence") or []
                for evidence in resume_evidence[:2]:
                    text = str(evidence.get("text") or "")
                    if text:
                        evidence_track.append({"kind": "resume_claim", "text": text})
            question_kind = str(row.get("question_kind") or "adaptive")
            evidence_track.append(
                {
                    "kind": "anchor_question" if question_kind == "anchor" else "adaptive_question",
                    "round_id": row.get("id"),
                    "question_text": str(row.get("question_text") or "")[:300],
                    "question_kind": question_kind,
                }
            )
            evidence_track.append(
                {
                    "kind": "answer_evidence",
                    "round_id": row.get("id"),
                    "score": row.get("score"),
                    "confidence": row.get("judge_confidence"),
                    "low_confidence": _round_low_confidence(row),
                    "spans": _round_evidence_spans(row),
                }
            )
        verification.append(
            {
                "competency_id": competency_id,
                "name": competency.get("name"),
                "weight": competency.get("weight"),
                "must_have": competency.get("must_have"),
                "target_level": competency.get("level") or competency_snapshot.get("level"),
                "required_score": required_score,
                "level_expectation": competency.get("level_expectation") or "",
                "status": status,
                "score": best_score,
                "best_score": best_score,
                "low_confidence": low_confidence,
                "anchor_done": anchor_done,
                "tested_round_count": len(tested),
                "conclusion": conclusion,
                "evidence_track": evidence_track,
            }
        )
    return verification


def build_project_claim_verification(
    resume_snapshot: dict[str, Any] | None,
    candidate_state: dict[str, Any] | None,
    rounds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Project claim verification matrix for the report.

    Technical skill (avg score on the related rounds) and claim truthfulness
    (verification_status) are reported separately: a high score on a related
    question never equals "the resume claim is truthful".  ``verified`` only
    means the candidate demonstrated the claim with project-claim-relevant
    evidence at the required score and confidence.
    """
    projects = [item for item in (resume_snapshot or {}).get("projects", []) if isinstance(item, dict) and item.get("project_id")]
    attack_map = (candidate_state or {}).get("project_attack_map") or []
    claim_state = (candidate_state or {}).get("project_claim_state") or {}

    related_rounds: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rounds:
        actions = row.get("planner_actions")
        if not isinstance(actions, list):
            continue
        for action in reversed(actions):
            if isinstance(action, dict) and action.get("target_claim_id"):
                related_rounds[str(action.get("target_claim_id"))].append(row)
                break

    matrix: list[dict[str, Any]] = []
    for project in projects:
        project_id = str(project.get("project_id") or "")
        for claim in (project.get("claims") or []):
            if not isinstance(claim, dict) or not claim.get("claim_id"):
                continue
            claim_id = str(claim.get("claim_id") or "")
            targets = [item for item in attack_map if str(item.get("claim_id")) == claim_id and str(item.get("project_id")) == project_id]
            dimensions = []
            for target in targets:
                target_id = str(target.get("target_id") or "")
                row = claim_state.get(target_id) or {}
                dimensions.append(
                    {
                        "dimension": str(target.get("dimension") or ""),
                        "status": str(row.get("status") or ProjectClaimStatus.UNTESTED.value),
                        "attempt_count": int(row.get("attempt_count") or 0),
                        "followup_depth": int(row.get("followup_depth") or 0),
                        "answered_evidence": list(row.get("answered_evidence") or []),
                        "related_question_ids": list(row.get("related_question_ids") or []),
                    }
                )
            rows = related_rounds.get(claim_id, [])
            scores = [float(row["score"]) for row in rows if row.get("score") is not None]
            tested_round_count = len(rows)
            average = _average(scores)

            statuses = [item["status"] for item in dimensions]
            if "contradiction" in statuses:
                status = ProjectClaimStatus.CONTRADICTION.value
            elif "disputed" in statuses:
                status = ProjectClaimStatus.DISPUTED.value
            elif "low_confidence" in statuses:
                status = ProjectClaimStatus.LOW_CONFIDENCE.value
            elif "partial" in statuses:
                status = ProjectClaimStatus.PARTIAL.value
            elif "verified" in statuses:
                status = ProjectClaimStatus.VERIFIED.value
            else:
                status = ProjectClaimStatus.UNTESTED.value

            if status == ProjectClaimStatus.UNTESTED.value:
                conclusion = "本场未对该项目声明进行深挖。"
            elif status == ProjectClaimStatus.CONTRADICTION.value:
                conclusion = "回答与本声明存在矛盾，需要后续澄清复核。"
            elif status == ProjectClaimStatus.DISPUTED.value:
                conclusion = "回答无法支撑该声明，项目陈述与实测存在差距。"
            elif status == ProjectClaimStatus.VERIFIED.value:
                conclusion = "候选人以项目相关证据、达标得分与足够置信度演示了该声明。"
            elif status == ProjectClaimStatus.PARTIAL.value:
                conclusion = "部分演示了该声明，仍有维度/边界未验证。"
            else:
                conclusion = "相关回答置信度不足，不构成结论。"
            matrix.append(
                {
                    "project_id": project_id,
                    "project_name": str(project.get("name") or ""),
                    "claim_id": claim_id,
                    "claim_text": str(claim.get("text") or "")[:500],
                    "claim_type": str(claim.get("claim_type") or ""),
                    "evidence_span": str(claim.get("evidence_span") or "")[:500],
                    "dimensions": dimensions,
                    "verification_status": status,
                    "score": average,
                    "tested_round_count": tested_round_count,
                    "conclusion": conclusion,
                }
            )
    return matrix


def build_report(
    rounds: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    resume_snapshot: dict[str, Any] | None = None,
    job_snapshot: dict[str, Any] | None = None,
    match_snapshot: list[dict[str, Any]] | None = None,
    competency_snapshot: dict[str, Any] | None = None,
    candidate_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    completed = [row for row in rounds if row.get("status") == RoundStatus.COMPLETED.value and row.get("score") is not None]
    final_scores = [float(row["score"]) for row in completed]
    initial_scores = [float(row.get("initial_score") if row.get("initial_score") is not None else row["score"]) for row in completed]
    followed = [float(row["score"]) for row in completed if int(row.get("followup_count") or 0) > 0]
    by_topic: dict[str, list[float]] = defaultdict(list)
    by_difficulty: dict[str, list[float]] = defaultdict(list)
    by_category: dict[str, list[float]] = defaultdict(list)
    by_question_type: dict[str, list[float]] = defaultdict(list)
    followup_total = 0
    for row in completed:
        score = float(row["score"])
        by_topic[str(row.get("topic", "unknown"))].append(score)
        by_difficulty[str(row.get("difficulty", "unknown"))].append(score)
        by_category[str(row.get("category", "unknown"))].append(score)
        question_type = str(row.get("question_type") or ("coding" if row.get("category") == "leetcode" else "theory"))
        by_question_type[question_type].append(score)
        followup_total += int(row.get("followup_count") or 0)
    ability_scores = {key: _average(value) for key, value in sorted(by_topic.items())}
    difficulty_scores = {key: _average(value) for key, value in sorted(by_difficulty.items())}
    category_scores = {key: _average(value) for key, value in sorted(by_category.items())}
    question_type_scores = {key: _average(value) for key, value in sorted(by_question_type.items())}
    ranked = sorted(ability_scores.items(), key=lambda item: (item[1], item[0]))
    weaknesses = [{"topic": topic, "score": score, "priority": index + 1} for index, (topic, score) in enumerate(ranked[:3]) if score < 3.5]
    strengths = [{"topic": topic, "score": score} for topic, score in sorted(ability_scores.items(), key=lambda item: (-item[1], item[0])) if score >= 3][:3]
    training_plan = []
    for index, weakness in enumerate(weaknesses[:3], 1):
        training_plan.append(
            {
                "order": index,
                "topic": weakness["topic"],
                "action": f"围绕 {weakness['topic']} 完成知识梳理、2 道场景题和 1 次口述复盘。",
                "success_criteria": "不依赖提示完整覆盖关键评分点，并能解释一个常见误区。",
            }
        )
    while len(training_plan) < 3:
        index = len(training_plan) + 1
        training_plan.append(
            {
                "order": index,
                "topic": "综合复盘",
                "action": "重答本场低于 3 分的题目，并对照证据整理答案结构。",
                "success_criteria": "重答平均分达到 3 分，且不再需要同方向追问。",
            }
        )
    overall = _average(final_scores)
    recommended_difficulty = str(profile.get("initial_difficulty", Difficulty.MEDIUM.value))
    if overall >= 3.5:
        recommended_difficulty = compute_next_difficulty(recommended_difficulty, 4, 4)
    elif overall < 2:
        recommended_difficulty = compute_next_difficulty(recommended_difficulty, 1, None)
    metrics = {
        "overall_score": overall,
        "initial_answer_average": _average(initial_scores),
        "post_followup_average": _average(followed),
        "difficulty_scores": difficulty_scores,
        "category_scores": category_scores,
        "question_type_scores": question_type_scores,
        "followup_count": followup_total,
        "question_count": len(completed),
        "recommended_role": profile.get("target_role", "cs_general"),
        "recommended_difficulty": recommended_difficulty,
    }
    stars = round(min(5.0, max(0.0, overall / 4 * 5)) * 2) / 2
    lines = [
        "# CS 模拟面试复盘",
        "",
        f"本场完成 {len(completed)} 道题，综合得分 {overall:.2f}/4，星级 {stars:.1f}/5。",
        "",
        "## 优势",
    ]
    lines.extend([f"- {item['topic']}：{item['score']:.2f}/4" for item in strengths] or ["- 尚未形成稳定优势领域。"])
    lines.extend(["", "## 优先改进", *[f"- {item['topic']}：{item['score']:.2f}/4" for item in weaknesses]])
    lines.extend(["", "## 三步训练计划", *[f"{item['order']}. {item['action']}" for item in training_plan]])
    result = {
        "overall_score": overall,
        "star_rating": stars,
        "ability_scores": ability_scores,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "training_plan": training_plan,
        "metrics": metrics,
        "report_markdown": "\n".join(lines),
        "report_version": REPORT_VERSION,
    }
    claimed_skills = (resume_snapshot or {}).get("claimed_skills") or []
    if claimed_skills:
        skill_verification = build_skill_verification(claimed_skills, rounds)
        result["skill_verification"] = skill_verification
        lines.append("")
        lines.append("## 简历技能验证")
        status_label = {
            "verified": "实测通过",
            "partial": "部分达标",
            "disputed": "与描述有差距",
            "not_tested": "本场未覆盖",
        }
        for item in skill_verification:
            label = status_label.get(item["status"], item["status"])
            score_text = f"{item['avg_score']:.1f}/4" if item["avg_score"] is not None else "未考"
            lines.append(f"- {item['skill']}（简历声称 {item['claimed_level']}）：{label}，相关题目 {score_text}。")
        result["report_markdown"] = "\n".join(lines)
    if job_snapshot:
        matrix = build_jd_verification_matrix(job_snapshot, match_snapshot or [], rounds)
        result["jd_verification_matrix"] = matrix
        lines.extend(["", "## JD 能力验证矩阵"])
        status_label = {
            VerificationStatus.VERIFIED.value: "已验证",
            VerificationStatus.PARTIAL.value: "部分验证",
            VerificationStatus.DISPUTED.value: "存在争议",
            VerificationStatus.UNTESTED.value: "未覆盖",
        }
        for item in matrix:
            score_text = f"{item['score']:.1f}/4" if item["score"] is not None else "未考"
            lines.append(f"- {item['requirement_text']}：{status_label[item['verification_status']]}，{score_text}，简历匹配 {item['resume_claim_status']}。")
        result["report_markdown"] = "\n".join(lines)
    if competency_snapshot:
        competency_verification = build_competency_verification(
            competency_snapshot,
            rounds,
            job_snapshot=job_snapshot,
            match_snapshot=match_snapshot or [],
            candidate_state=candidate_state,
        )
        result["competency_verification"] = competency_verification
        lines.extend(["", "## 能力验证结论"])
        status_label = {
            "verified": "已验证",
            "partial": "部分验证",
            "insufficient_evidence": "证据不足",
            "contradiction": "存在矛盾",
            "uncovered": "未覆盖",
        }
        for item in competency_verification:
            label = status_label.get(item["status"], item["status"])
            score_text = f"{item['score']:.1f}/4" if item["score"] is not None else "未考"
            lines.append(f"- {item['name']}：{label}，{score_text}。{item['conclusion']}")
        result["report_markdown"] = "\n".join(lines)
    if resume_snapshot and (resume_snapshot.get("projects") or []):
        project_verification = build_project_claim_verification(resume_snapshot, candidate_state, rounds)
        result["project_claim_verification"] = project_verification
        lines.extend(["", "## 项目声明验真矩阵"])
        lines.append("技术能力得分（相关题目平均分）与项目声明可信度分开展示；“已验证”仅表示候选人以项目相关证据、达标得分与足够置信度演示了该声明。")
        status_label = {
            "verified": "已验证",
            "partial": "部分验证",
            "disputed": "存在差距",
            "contradiction": "存在矛盾",
            "low_confidence": "置信不足",
            "untested": "未覆盖",
        }
        for item in project_verification:
            score_text = f"{item['score']:.1f}/4" if item["score"] is not None else "未考"
            dims = "、".join(sorted({entry["dimension"] for entry in item["dimensions"]})) or "无"
            lines.append(f"- {item['project_name']}｜{item['claim_text']}（{dims}）：{status_label[item['verification_status']]}，{score_text}。{item['conclusion']}")
        result["report_markdown"] = "\n".join(lines)
    return result


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right)) / denominator if denominator else 0.0
