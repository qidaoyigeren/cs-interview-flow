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
REPORT_VERSION = "cs-interview-report-v3"
JOB_EXTRACTION_VERSION = "cs-interview-jd-extraction-v1"
ANSWER_STATE_VERSION = "cs-interview-answer-state-v2"
PLANNER_VERSION = "cs-interview-planner-v1"
MAX_ANSWER_CHARS = 20_000
MAX_SOURCE_CHARS = 50_000
MAX_JOB_CHARS = 50_000
MAX_COMPILER_OUTPUT = 8_000
SUPPORTED_LANGUAGES = {"python", "go", "javascript"}
CLAIMED_LEVELS = {"fluent", "experienced", "proficient", "familiar", "beginner"}
EXTRACTION_VERSION = "cs-interview-resume-extraction-v1"


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


class PlannerActionKind(StrEnum):
    FOLLOW_UP_CURRENT_CLAIM = "follow_up_current_claim"
    VERIFY_RESUME_CLAIM = "verify_resume_claim"
    VERIFY_JD_REQUIREMENT = "verify_jd_requirement"
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


def validate_resume_extraction(raw: dict[str, Any]) -> dict[str, Any]:
    """Deterministically clamp/validate LLM resume extraction into the stored shape.

    Mirrors validate_judge_result: pure, strict enough to reject unusable output,
    tolerant enough to keep a mostly-good extraction. Raises DomainError on output
    that contains no usable candidate information at all.
    """
    if not isinstance(raw, dict):
        raise DomainError("invalid_extraction", "Resume extraction must be a JSON object.")

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

    stack = _string_list("technology_stack")
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
        topics = list(dict.fromkeys(topics))
        claimed.append({"skill": skill, "claimed_level": claimed_level, "topics": topics})
    if claimed:
        result["claimed_skills"] = claimed

    projects: list[dict[str, Any]] = []
    for item in raw.get("projects", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name or len(name) > 255:
            continue
        summary = str(item.get("summary") or "").strip()[:2000]
        projects.append(
            {
                "name": name,
                "role": str(item.get("role") or "").strip()[:128],
                "summary": summary,
                "skills": _string_list_from(item, "skills"),
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


def _normalized_phrase(value: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff+#.]+", "", str(value).strip().lower())


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


def initial_candidate_state() -> dict[str, Any]:
    return asdict(CandidateState([], [], [], [], [], [], [], [], ""))


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


def _exact_answer_span(value: Any, answer: str, *, limit: int = 500) -> str:
    span = str(value or "").strip()[:limit]
    return span if span and span in answer else ""


def validate_answer_state(raw: dict[str, Any], answer: str, known_claims: Iterable[str] = ()) -> dict[str, Any]:
    """Validate answer-derived claims without treating them as technical truth."""

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
        "project_facts": facts("project_facts", "fact"),
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


def merge_candidate_state(
    state: dict[str, Any],
    answer_state: dict[str, Any],
    judge: JudgeResult,
    *,
    requirement_id: str | None,
    target_topic: str,
    completed: bool,
    targeted_claim_facts: Iterable[str] = (),
    resolved_contradiction_ids: Iterable[str] = (),
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
    prior_unverified_facts = list(result.get("newly_claimed_facts") or [])
    new_facts = [*answer_state.get("newly_claimed_facts", []), *answer_state.get("project_facts", [])]
    extend_unique("newly_claimed_facts", new_facts, lambda item: _normalized_phrase(item.get("fact")))
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
    if completed and judge.score >= 3:
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
    return result


def update_interview_plan(
    plan: list[dict[str, Any]],
    requirement_id: str | None,
    *,
    score: int | None,
    completed: bool,
) -> list[dict[str, Any]]:
    updated = []
    for item in plan:
        row = dict(item)
        if requirement_id and row.get("requirement_id") == requirement_id:
            row["attempt_count"] = int(row.get("attempt_count") or 0) + 1
            if completed:
                row["status"] = "verified" if score is not None and score >= 3 else "partial" if score == 2 else "disputed"
            else:
                row["status"] = "in_progress"
        updated.append(row)
    return updated


def _planner_input_hashes(plan: list[dict[str, Any]], candidate_state: dict[str, Any], rounds: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "plan_hash": payload_hash({"plan": plan}),
        "candidate_state_hash": payload_hash({"candidate_state": candidate_state}),
        "rounds_hash": payload_hash({"rounds": rounds}),
    }


def choose_planner_action(
    plan: list[dict[str, Any]],
    candidate_state: dict[str, Any],
    rounds: list[dict[str, Any]],
    *,
    remaining_question_budget: int,
    current_difficulty: str,
) -> PlannerAction:
    input_hashes = _planner_input_hashes(plan, candidate_state, rounds)
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
    if not eligible:
        return PlannerAction(
            PlannerActionKind.FINISH_INTERVIEW.value,
            None,
            None,
            "所有可映射的 JD 要求均已覆盖。",
            {"remaining_question_budget": remaining_question_budget},
            target_difficulty=current_difficulty,
            decision_audit={
                "reason_branch": "no_eligible",
                "eliminated": [
                    {"requirement_id": str(item.get("requirement_id")), "topic_id": str(item.get("topic_id")), "reason": "verified_or_terminal_status"}
                    for item in terminal_items
                ],
                "budget": {"remaining_question_budget": remaining_question_budget},
                "input": input_hashes,
            },
        )
    unattempted = [item for item in eligible if item.get("status") == "pending" and int(item.get("attempt_count") or 0) == 0]
    guard_active = bool(unattempted and remaining_question_budget <= len(unattempted))
    if guard_active:
        # Preserve remaining capacity for requirements that have never been
        # tested. Re-visiting a partial/disputed item is allowed only when it
        # cannot starve untouched JD requirements.
        eligible = unattempted
    recent_topics = [str(row.get("topic")) for row in rounds[-2:]]
    new_claim_topics = {str(topic) for fact in candidate_state.get("newly_claimed_facts", []) for topic in fact.get("topic_ids", [])}
    contradiction_topics = {str(topic) for contradiction in candidate_state.get("contradictions", []) if contradiction.get("status") == "unresolved" for topic in contradiction.get("topic_ids", [])}

    def breakdown(item: dict[str, Any]) -> dict[str, Any]:
        topic = str(item.get("topic_id"))
        attempts = int(item.get("attempt_count") or 0)
        contradiction_bonus = 0.9 if topic in contradiction_topics else 0
        new_claim_bonus = 0.55 if contradiction_bonus == 0 and topic in new_claim_topics else 0
        untested_bonus = 0.35 if attempts == 0 else 0
        repeat_penalty = 0.6 if topic in recent_topics else 0
        attempt_penalty = min(attempts, 8) * 0.25
        priority = float(item.get("priority") or 0)
        rank_score = round(priority + contradiction_bonus + new_claim_bonus + untested_bonus - repeat_penalty - attempt_penalty, 6)
        jd_weight = item.get("jd_weight")
        return {
            "requirement_id": str(item.get("requirement_id")),
            "topic_id": topic,
            "priority": priority,
            "jd_weight": round(float(jd_weight), 6) if jd_weight is not None else None,
            "risk_multiplier": item.get("risk_multiplier"),
            "category_multiplier": item.get("category_multiplier"),
            "contradiction_bonus": contradiction_bonus,
            "new_claim_bonus": new_claim_bonus,
            "untested_bonus": untested_bonus,
            "repeat_penalty": repeat_penalty,
            "attempt_penalty": attempt_penalty,
            "rank_score": rank_score,
        }

    candidates = [breakdown(item) for item in eligible]
    candidates.sort(key=lambda row: (-row["rank_score"], row["requirement_id"]))
    selected = min(eligible, key=lambda item: (-breakdown(item)["rank_score"], str(item.get("requirement_id"))))
    preferred_type = str(selected.get("preferred_question_type") or "scenario")
    strategy = str(selected.get("verification_strategy") or PlannerActionKind.VERIFY_JD_REQUIREMENT.value)
    selected_topic = str(selected.get("topic_id"))
    if selected_topic in contradiction_topics:
        action = PlannerActionKind.RESOLVE_CONTRADICTION.value
    elif preferred_type == "coding":
        action = PlannerActionKind.ASK_CODING_QUESTION.value
    elif rounds and selected_topic != str(rounds[-1].get("topic")):
        action = PlannerActionKind.SWITCH_TOPIC.value
    else:
        action = strategy
    reasons = [str(selected.get("objective") or "验证 JD 要求")]
    if selected_topic in contradiction_topics:
        reasons.append("该主题存在尚未解决的回答矛盾")
    elif str(selected.get("topic_id")) in new_claim_topics:
        reasons.append("候选人刚补充了相关新声明，需要验证")
    return PlannerAction(
        action,
        str(selected.get("requirement_id")),
        selected_topic,
        "；".join(reasons)[:1000],
        {
            "remaining_question_budget": remaining_question_budget,
            "covered_requirement_ids": list(candidate_state.get("covered_requirement_ids") or []),
            "new_claim_topics": sorted(new_claim_topics),
            "contradiction_topics": sorted(contradiction_topics),
            "recent_topics": recent_topics,
        },
        # The plan records the desired level, but the session difficulty is the
        # program-controlled boundary for the next question.
        target_difficulty=current_difficulty,
        preferred_question_type=preferred_type,
        decision_audit={
            "reason_branch": "planner",
            "candidates": candidates,
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
                    if item.get("status") != "pending" or int(item.get("attempt_count") or 0) > 0
                ]
                if guard_active
                else []
            ),
            "selected": {
                "requirement_id": str(selected.get("requirement_id")),
                "topic_id": selected_topic,
                "action": action,
                "reason": "；".join(reasons)[:1000],
            },
            "budget": {"remaining_question_budget": remaining_question_budget, "contradiction_guard": guard_active},
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
) -> PlannerAction:
    followup_count = int(round_data.get("followup_count") or 0)
    target_topic = str(round_data.get("topic") or "")
    requirement_id = str(round_data.get("target_requirement_id") or "") or None
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
                },
                followup_focus=f"请澄清“{contradiction.get('statement')}”与“{contradiction.get('conflicts_with')}”之间的差异",
                target_contradiction_id=contradiction_id,
                target_difficulty=current_difficulty,
                preferred_question_type=str(round_data.get("question_type") or "scenario"),
                decision_audit={
                    "reason_branch": "contradiction",
                    "followup_budget": {"followup_count": followup_count, "max_followups": max_followups},
                    "target_contradiction_id": contradiction_id,
                    "target_claim_fact": "",
                },
            )
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


def build_report(
    rounds: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    resume_snapshot: dict[str, Any] | None = None,
    job_snapshot: dict[str, Any] | None = None,
    match_snapshot: list[dict[str, Any]] | None = None,
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
    return result


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return sum(x * y for x, y in zip(left, right)) / denominator if denominator else 0.0
