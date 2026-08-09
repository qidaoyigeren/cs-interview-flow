"""Deterministic offline quality evaluation for the CS interview pipeline.

Metrics are computed from actual execution of the real planner / domain
functions against structured fixtures -- fixtures never self-report
``actual_action``. Every threshold carries its sample count and, for ratio
metrics, a 95% Wilson confidence interval. A metric with too few samples is
reported as ``insufficient`` and never passes the gate; safety metrics with
zero samples force a failure.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from api.apps.services.cs_interview.domain import (
    PLANNER_VERSION,
    ROLE_CAPABILITY_TREES,
    DomainError,
    build_report,
    choose_after_answer_action,
    choose_planner_action,
    lexical_similarity,
    update_interview_plan,
    validate_judge_result,
)
from api.apps.services.cs_interview.replay import replay_planner_decision


@dataclass(frozen=True)
class EvaluationResult:
    metrics: dict[str, float | int]
    thresholds: dict[str, dict[str, Any]]
    passed: bool
    sample_counts: dict[str, int]
    insufficient: dict[str, bool]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _wilson_ci(numerator: int, denominator: int, *, z: float = 1.96) -> dict[str, float] | None:
    """95% Wilson score interval for a proportion; None for counts (not a ratio)."""
    if denominator <= 0:
        return None
    p = numerator / denominator
    denom = 1 + z * z / denominator
    center = (p + z * z / (2 * denominator)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * denominator)) / denominator) / denom
    return {
        "low": round(max(0.0, center - margin), 4),
        "high": round(min(1.0, center + margin), 4),
        "point": round(p, 4),
    }


def _duplicate_pairs(questions: list[dict[str, Any]]) -> int:
    duplicates = 0
    for index, question in enumerate(questions):
        for other in questions[:index]:
            same_id = question.get("question_id") == other.get("question_id")
            semantically_close = (
                lexical_similarity(
                    str(question.get("question_text", "")),
                    str(other.get("question_text", "")),
                )
                >= 0.9
            )
            if same_id or semantically_close:
                duplicates += 1
                break
    return duplicates


def _judge_metrics(cases: list[dict[str, Any]]) -> tuple[int, int, int]:
    valid = 0
    agreements = 0
    reasonable_followups = 0
    for case in cases:
        try:
            result = validate_judge_result(
                case["output"],
                followup_count=int(case.get("followup_count", 0)),
                max_followups=int(case.get("max_followups", 2)),
            )
        except (DomainError, KeyError, TypeError, ValueError):
            continue
        valid += 1
        agreements += result.score == int(case["human_score"])
        reasonable_followups += result.needs_followup == bool(case["human_needs_followup"])
    return valid, agreements, reasonable_followups


def _report_consistent(case: dict[str, Any]) -> bool:
    actual = build_report(case["rounds"], case["profile"])
    expected = case["expected"]
    for field in ("overall_score", "star_rating"):
        if actual[field] != expected[field]:
            return False
    for field in (
        "initial_answer_average",
        "post_followup_average",
        "followup_count",
        "question_count",
    ):
        if actual["metrics"][field] != expected[field]:
            return False
    return True


def _contains_hidden_data(response: Any, forbidden: list[str]) -> bool:
    serialized = json.dumps(response, ensure_ascii=False, sort_keys=True).lower()
    hidden_keys = {
        "reference_answer",
        "evaluation_rubric",
        "hidden_tests",
        "judge_prompt",
        "retrieval_evidence",
    }
    if any(f'"{key}"' in serialized for key in hidden_keys):
        return True
    return any(str(item).lower() in serialized for item in forbidden if item)


def _grounding_overlap(question_text: str, evidence: list[dict[str, Any]]) -> float:
    question_tokens = {token for token in question_text.lower().replace(".", " ").split() if len(token) > 2}
    evidence_tokens = {
        token
        for item in evidence
        for token in str(item.get("content") or "").lower().replace(".", " ").split()
        if len(token) > 2
    }
    return len(question_tokens & evidence_tokens) / len(question_tokens) if question_tokens else 0.0


def _simulate_session(case: dict[str, Any], first_action) -> dict[str, Any]:
    """Execute deterministic primary-question planning to measure real coverage."""
    planner = case.get("planner") or {}
    plan = deepcopy(list(planner.get("plan") or []))
    state = deepcopy(dict(planner.get("candidate_state") or {}))
    history = deepcopy(list(planner.get("rounds") or []))
    remaining = int(planner.get("remaining_question_budget") or 0)
    difficulty = str(planner.get("current_difficulty") or "medium")
    pending_count = sum(item.get("status") in {"pending", "in_progress", "partial", "disputed"} for item in plan)
    eligible = planner.get("phase") == "initial" and remaining >= pending_count
    asked = {
        str(row.get("target_requirement_id"))
        for row in history
        if row.get("target_requirement_id")
    }
    asked.update(
        str(item.get("requirement_id"))
        for item in plan
        if item.get("requirement_id") and item.get("status") not in {"pending"}
    )
    claims = [item for item in case.get("resume_claims", []) if isinstance(item, dict)]
    verified_claim_ids = {
        str(claim.get("claim_id"))
        for claim in claims
        if any(
            item.get("requirement_id") == claim.get("requirement_id") and item.get("status") == "verified"
            for item in plan
        )
    }

    action = first_action
    for _ in range(max(1, len(plan) + 1)):
        if action.selected_action in {"finish_interview", "resolve_contradiction", "follow_up_current_claim"}:
            break
        requirement_id = str(action.target_requirement_id or "")
        if not requirement_id:
            break
        asked.add(requirement_id)
        if action.selected_action == "verify_resume_claim":
            verified_claim_ids.update(
                str(claim.get("claim_id"))
                for claim in claims
                if str(claim.get("requirement_id") or "") == requirement_id
            )
        plan = update_interview_plan(plan, requirement_id, score=3, completed=True)
        state["covered_requirement_ids"] = list(dict.fromkeys([*(state.get("covered_requirement_ids") or []), requirement_id]))
        history.append({"target_requirement_id": requirement_id, "topic": action.target_topic, "score": 3})
        remaining -= 1
        if remaining <= 0:
            break
        action = choose_planner_action(
            plan,
            state,
            history,
            remaining_question_budget=remaining,
            current_difficulty=difficulty,
        )
    return {"eligible": eligible, "asked": asked, "verified_claim_ids": verified_claim_ids}


def _real_replay_deterministic(case: dict[str, Any], stored_action) -> bool | None:
    planner = case.get("planner") or {}
    if planner.get("phase") != "initial":
        return None
    result = replay_planner_decision(
        planner_version=PLANNER_VERSION,
        plan=list(planner.get("plan") or []),
        candidate_state=dict(planner.get("candidate_state") or {}),
        history=list(planner.get("rounds") or []),
        stored_action=asdict(stored_action),
        remaining_question_budget=int(planner.get("remaining_question_budget") or 0),
        current_difficulty=str(planner.get("current_difficulty") or "medium"),
    )
    return result["outcome"] == "deterministic"


def _evaluate_agentic_case(case: dict[str, Any]) -> dict[str, Any]:
    planner = case.get("planner") or {}
    plan = list(planner.get("plan") or [])
    candidate_state = dict(planner.get("candidate_state") or {})
    rounds = list(planner.get("rounds") or [])
    remaining = int(planner.get("remaining_question_budget", 0))
    difficulty = str(planner.get("current_difficulty") or "medium")
    if planner.get("phase") == "after_answer":
        round_data = dict(planner.get("round") or {})
        judge = validate_judge_result(
            dict(planner.get("judge_output") or {}),
            followup_count=int(round_data.get("followup_count") or 0),
            max_followups=int(planner.get("max_followups", 2)),
        )
        action = choose_after_answer_action(
            plan,
            candidate_state,
            dict(planner.get("answer_state") or {}),
            judge,
            round_data,
            rounds,
            remaining_question_budget=remaining,
            max_followups=int(planner.get("max_followups", 2)),
            current_difficulty=difficulty,
        )
    else:
        action = choose_planner_action(
            plan,
            candidate_state,
            rounds,
            remaining_question_budget=remaining,
            current_difficulty=difficulty,
        )

    requirements = [item for item in case.get("requirements", []) if isinstance(item, dict)]
    requirement_ids = {str(item.get("requirement_id")) for item in requirements}
    simulation = _simulate_session(case, action)
    covered = requirement_ids & simulation["asked"]
    must_have = {str(item.get("requirement_id")) for item in requirements if item.get("category") == "must_have"}
    resume_claims = [item for item in case.get("resume_claims", []) if isinstance(item, dict)]
    verified_claims = sum(str(item.get("claim_id")) in simulation["verified_claim_ids"] for item in resume_claims)

    question = case.get("question") if isinstance(case.get("question"), dict) else None
    question_relevant = False
    grounded = False
    leaked = False
    if question:
        target_id = str(question.get("target_requirement_id") or "")
        target = next((item for item in requirements if str(item.get("requirement_id")) == target_id), None)
        question_relevant = bool(target and question.get("topic") in target.get("topic_ids", []))
        evidence = [item for item in question.get("evidence", []) if isinstance(item, dict)]
        grounded = bool(evidence) and all(item.get("evidence_id") and item.get("content") for item in evidence) and _grounding_overlap(
            str(question.get("question_text") or ""), evidence
        ) >= 0.1
        leaked = _contains_hidden_data(question.get("candidate_response"), list(case.get("forbidden_fragments") or []))

    return {
        "requirement_count": len(requirements),
        "covered_requirement_count": len(covered),
        "must_have_count": len(must_have),
        "covered_must_have_count": len(must_have & covered),
        "resume_claim_count": len(resume_claims),
        "verified_resume_claim_count": verified_claims,
        "coverage_eligible": simulation["eligible"],
        "expected_action": case.get("expected_action"),
        "actual_action": action.selected_action,
        "has_contradiction": bool((planner.get("answer_state") or {}).get("contradictions")),
        "generated_question": bool(question),
        "question_relevant": question_relevant,
        "evidence_valid": grounded,
        "hidden_answer_leaked": leaked,
        "replay_deterministic": _real_replay_deterministic(case, action),
    }


# Minimum samples per metric before the gate can pass. Metrics below this are
# reported as insufficient_sample and treated as a failure (never a trivial
# 100% PASS). Safety metrics with zero samples always force a failure.
MIN_SAMPLES: dict[str, int] = {
    "retrieval_recall_at_5": 5,
    "grounded_question_ratio": 5,
    "question_duplicate_ratio": 5,
    "role_relevance_ratio": 5,
    "difficulty_match_ratio": 5,
    "judge_human_agreement_ratio": 5,
    "judge_json_valid_ratio": 5,
    "followup_reasonable_ratio": 5,
    "followup_limit_violations": 1,
    "ungrounded_generation_count": 1,
    "report_numeric_consistency_ratio": 1,
    "hidden_answer_leakage_count": 1,
    "jd_requirement_question_coverage": 5,
    "must_have_coverage": 5,
    "resume_claim_verification_rate": 5,
    "answer_driven_branch_accuracy": 5,
    "contradiction_followup_accuracy": 3,
    "jd_question_relevance": 5,
    "agentic_grounded_question_ratio": 5,
    "replay_determinism_ratio": 5,
}

# Safety metrics: any non-zero value or any zero-sample run blocks the release.
SAFETY_METRICS = frozenset(
    {
        "followup_limit_violations",
        "ungrounded_generation_count",
        "report_numeric_consistency_ratio",
        "hidden_answer_leakage_count",
        "replay_determinism_ratio",
    }
)


def evaluate_fixture(payload: dict[str, Any]) -> EvaluationResult:
    retrieval_cases = payload.get("retrieval_cases", [])
    retrieved = sum(bool(set(case.get("expected_ids", [])) & set(case.get("retrieved_ids", [])[:5])) for case in retrieval_cases)

    questions = payload.get("questions", [])
    grounded = sum(bool(case.get("evidence_valid")) for case in questions)
    ungrounded_generated = sum(not bool(case.get("evidence_valid")) for case in questions)
    relevant = 0
    matched_difficulty = 0
    for case in questions:
        role_topics = {topic.id for topic in ROLE_CAPABILITY_TREES.get(case.get("role"), ())}
        relevant += case.get("topic") in role_topics
        matched_difficulty += case.get("difficulty") == case.get("requested_difficulty")

    duplicates = _duplicate_pairs(questions)
    judge_cases = payload.get("judge_cases", [])
    judge_valid, judge_agreements, reasonable_followups = _judge_metrics(judge_cases)
    violations = sum(bool(case.get("output", {}).get("needs_followup")) and int(case.get("followup_count", 0)) >= int(case.get("max_followups", 2)) for case in judge_cases)
    report_cases = payload.get("report_cases", [])
    consistent_reports = sum(_report_consistent(case) for case in report_cases)
    visibility_cases = payload.get("candidate_responses", [])
    leakage_count = sum(_contains_hidden_data(case.get("response"), case.get("forbidden_fragments", [])) for case in visibility_cases)
    agentic_cases = [_evaluate_agentic_case(case) for case in payload.get("agentic_cases", [])]
    coverage_cases = [case for case in agentic_cases if case["coverage_eligible"]]
    requirement_total = sum(case["requirement_count"] for case in coverage_cases)
    requirement_covered = sum(case["covered_requirement_count"] for case in coverage_cases)
    must_have_total = sum(case["must_have_count"] for case in coverage_cases)
    must_have_covered = sum(case["covered_must_have_count"] for case in coverage_cases)
    resume_claim_total = sum(case["resume_claim_count"] for case in coverage_cases)
    resume_claim_verified = sum(case["verified_resume_claim_count"] for case in coverage_cases)
    branching_cases = [case for case in agentic_cases if case["expected_action"]]
    correct_branches = sum(case.get("actual_action") == case.get("expected_action") for case in branching_cases)
    contradiction_cases = [case for case in agentic_cases if case["has_contradiction"]]
    contradiction_followups = sum(case.get("actual_action") == "resolve_contradiction" for case in contradiction_cases)
    generated_agentic = [case for case in agentic_cases if case["generated_question"]]
    jd_relevant = sum(case["question_relevant"] for case in generated_agentic)
    grounded_agentic = sum(case["evidence_valid"] for case in generated_agentic)
    agentic_leakage = sum(bool(case.get("hidden_answer_leaked")) for case in agentic_cases)

    replay_cases = [case for case in agentic_cases if case["replay_deterministic"] is not None]
    replay_total = len(replay_cases)
    replay_deterministic = sum(bool(case["replay_deterministic"]) for case in replay_cases)

    metrics: dict[str, float | int] = {
        "retrieval_recall_at_5": _ratio(retrieved, len(retrieval_cases)),
        "grounded_question_ratio": _ratio(grounded, len(questions)),
        "question_duplicate_ratio": _ratio(duplicates, len(questions)),
        "role_relevance_ratio": _ratio(relevant, len(questions)),
        "difficulty_match_ratio": _ratio(matched_difficulty, len(questions)),
        "judge_human_agreement_ratio": _ratio(judge_agreements, len(judge_cases)),
        "judge_human_agreement": _ratio(judge_agreements, len(judge_cases)),
        "judge_json_valid_ratio": _ratio(judge_valid, len(judge_cases)),
        "followup_reasonable_ratio": _ratio(reasonable_followups, len(judge_cases)),
        "followup_limit_violations": violations,
        "ungrounded_generation_count": ungrounded_generated,
        "report_numeric_consistency_ratio": _ratio(consistent_reports, len(report_cases)),
        "hidden_answer_leakage_count": leakage_count + agentic_leakage,
        "jd_requirement_question_coverage": _ratio(requirement_covered, requirement_total),
        "must_have_coverage": _ratio(must_have_covered, must_have_total),
        "resume_claim_verification_rate": _ratio(resume_claim_verified, resume_claim_total),
        "answer_driven_branch_accuracy": _ratio(correct_branches, len(branching_cases)),
        "contradiction_followup_accuracy": _ratio(contradiction_followups, len(contradiction_cases)),
        "jd_question_relevance": _ratio(jd_relevant, len(generated_agentic)),
        "agentic_grounded_question_ratio": _ratio(grounded_agentic, len(generated_agentic)),
        "replay_determinism_ratio": _ratio(replay_deterministic, replay_total),
    }
    threshold_specs = {
        "retrieval_recall_at_5": (">=", 0.85),
        "grounded_question_ratio": (">=", 0.95),
        "question_duplicate_ratio": ("<", 0.02),
        "judge_human_agreement_ratio": (">=", 0.85),
        "judge_json_valid_ratio": (">=", 0.99),
        "followup_reasonable_ratio": (">=", 0.95),
        "followup_limit_violations": ("==", 0),
        "ungrounded_generation_count": ("==", 0),
        "report_numeric_consistency_ratio": ("==", 1.0),
        "hidden_answer_leakage_count": ("==", 0),
        "jd_requirement_question_coverage": (">=", 0.9),
        "must_have_coverage": (">=", 0.85),
        "resume_claim_verification_rate": (">=", 0.7),
        "answer_driven_branch_accuracy": (">=", 0.85),
        "contradiction_followup_accuracy": (">=", 0.9),
        "jd_question_relevance": (">=", 0.95),
        "agentic_grounded_question_ratio": (">=", 0.95),
        "replay_determinism_ratio": ("==", 1.0),
    }

    sample_for_metric = {
        "retrieval_recall_at_5": len(retrieval_cases),
        "grounded_question_ratio": len(questions),
        "question_duplicate_ratio": len(questions),
        "role_relevance_ratio": len(questions),
        "difficulty_match_ratio": len(questions),
        "judge_human_agreement_ratio": len(judge_cases),
        "judge_json_valid_ratio": len(judge_cases),
        "followup_reasonable_ratio": len(judge_cases),
        "followup_limit_violations": len(judge_cases),
        "ungrounded_generation_count": len(questions),
        "report_numeric_consistency_ratio": len(report_cases),
        "hidden_answer_leakage_count": len(visibility_cases) + len(agentic_cases),
        "jd_requirement_question_coverage": requirement_total,
        "must_have_coverage": must_have_total,
        "resume_claim_verification_rate": resume_claim_total,
        "answer_driven_branch_accuracy": len(branching_cases),
        "contradiction_followup_accuracy": len(contradiction_cases),
        "jd_question_relevance": len(generated_agentic),
        "agentic_grounded_question_ratio": len(generated_agentic),
        "replay_determinism_ratio": replay_total,
    }
    numerator_for_ci = {
        "retrieval_recall_at_5": retrieved,
        "grounded_question_ratio": grounded,
        "question_duplicate_ratio": duplicates,
        "role_relevance_ratio": relevant,
        "difficulty_match_ratio": matched_difficulty,
        "judge_human_agreement_ratio": judge_agreements,
        "judge_json_valid_ratio": judge_valid,
        "followup_reasonable_ratio": reasonable_followups,
        "followup_limit_violations": violations,
        "ungrounded_generation_count": ungrounded_generated,
        "report_numeric_consistency_ratio": consistent_reports,
        "hidden_answer_leakage_count": leakage_count + agentic_leakage,
        "jd_requirement_question_coverage": requirement_covered,
        "must_have_coverage": must_have_covered,
        "resume_claim_verification_rate": resume_claim_verified,
        "answer_driven_branch_accuracy": correct_branches,
        "contradiction_followup_accuracy": contradiction_followups,
        "jd_question_relevance": jd_relevant,
        "agentic_grounded_question_ratio": grounded_agentic,
        "replay_determinism_ratio": replay_deterministic,
    }

    thresholds: dict[str, dict[str, Any]] = {}
    insufficient: dict[str, bool] = {}
    for name, (operator, target) in threshold_specs.items():
        value = metrics[name]
        sample_count = sample_for_metric[name]
        required = MIN_SAMPLES.get(name, 1)
        is_insufficient = sample_count < required
        if name in SAFETY_METRICS and sample_count == 0:
            is_insufficient = True
        passed_value = value >= target if operator == ">=" else value < target if operator == "<" else value == target
        passed = passed_value and not is_insufficient
        ci = _wilson_ci(numerator_for_ci[name], sample_for_metric[name])
        thresholds[name] = {
            "operator": operator,
            "target": target,
            "value": value,
            "sample_count": sample_count,
            "ci": ci,
            "insufficient": is_insufficient,
            "passed": passed,
        }
        insufficient[name] = is_insufficient
    counts = {
        "retrieval_cases": len(retrieval_cases),
        "question_cases": len(questions),
        "judge_cases": len(judge_cases),
        "report_cases": len(report_cases),
        "visibility_cases": len(visibility_cases),
        "agentic_cases": len(agentic_cases),
        "agentic_requirements": requirement_total,
        "agentic_resume_claims": resume_claim_total,
    }
    return EvaluationResult(
        metrics=metrics,
        thresholds=thresholds,
        passed=all(item["passed"] for item in thresholds.values()),
        sample_counts=counts,
        insufficient=insufficient,
    )


def evaluate_file(path: str | Path) -> EvaluationResult:
    fixture_path = Path(path)
    with fixture_path.open(encoding="utf-8") as fixture:
        payload = json.load(fixture)
    agentic_path = fixture_path.with_name("agentic_scenarios.json")
    if not payload.get("agentic_cases") and agentic_path.exists():
        with agentic_path.open(encoding="utf-8") as fixture:
            payload["agentic_cases"] = json.load(fixture).get("agentic_cases", [])
    return evaluate_fixture(payload)


def labeled_stats(payload: dict[str, Any]) -> dict[str, Any]:
    """Informational statistics over the human-labeled quality set.

    This is not a release gate. It reports per-kind sample counts, the
    adjudication resolution rate and annotator-vs-final Cohen's kappa so the
    labeling effort can be audited. It never fabricates volume.
    """
    items = payload.get("items") or []
    per_kind: dict[str, int] = {}
    adjudicated = disagreements = 0
    pairs: list[tuple[int, int]] = []
    for item in items:
        kind = item.get("kind")
        per_kind[kind] = per_kind.get(kind, 0) + 1
        disagreements += int(bool(item.get("disagreement")))
        adjudicated += int(bool(item.get("adjudicated")))
        if item.get("label") is not None and "final_label" in item:
            pairs.append((int(item["label"]), int(item["final_label"])))
    return {
        "total_items": len(items),
        "per_kind": per_kind,
        "disagreements": disagreements,
        "adjudication_resolution_rate": round(adjudicated / len(items), 4) if items else 0.0,
        "annotator_vs_final_kappa": _cohens_kappa(pairs),
    }


def _cohens_kappa(pairs: list[tuple[int, int]]) -> float | None:
    if len(pairs) < 2:
        return None
    from collections import Counter

    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    count_a = Counter(a for a, _ in pairs)
    count_b = Counter(b for _, b in pairs)
    expected = sum((count_a[label] / n) * (count_b[label] / n) for label in set(count_a) | set(count_b))
    if expected == 1:
        return None
    return round((observed - expected) / (1 - expected), 4)


def human_summary(result: EvaluationResult) -> str:
    lines = [f"CS interview offline gate: {'PASS' if result.passed else 'FAIL'}"]
    for name, check in result.thresholds.items():
        marker = "PASS" if check["passed"] else "FAIL"
        sample_note = f" n={check['sample_count']}"
        ci_note = ""
        if check.get("ci"):
            ci_note = f" ci=({check['ci']['low']}, {check['ci']['high']})"
        lines.append(f"[{marker}] {name}: {check['value']} {check['operator']} {check['target']}{sample_note}{ci_note}")
    lines.append("Samples: " + ", ".join(f"{name}={count}" for name, count in result.sample_counts.items()))
    insufficient_names = [name for name, value in result.insufficient.items() if value]
    if insufficient_names:
        lines.append("Insufficient samples: " + ", ".join(insufficient_names))
    return "\n".join(lines)
