"""Tests for the CompetencySpec / rubric / evidence-judge / planner-v2 upgrade.

Covers the acceptance requirements: score anchors 0..4, evidence-span
truthfulness, high-score-without-evidence rejection, code-result conflicts,
must-have anchor coverage, uncovered status, adaptive-followup safety, planner
determinism, replay with snapshots, low-confidence review state, DTO privacy
and report/evidence consistency. No LLM / DB / Redis / runner.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from api.apps.services.cs_interview.competencies import (
    COMPETENCY_CATALOG,
    build_competency_catalog,
    build_rubric_snapshot,
    normalize_competency_snapshot,
    validate_competency_spec,
    validate_rubric_snapshot,
    validate_score_anchors,
)
from api.apps.services.cs_interview.domain import (
    DomainError,
    RubricScore,
    build_competency_verification,
    build_report,
    choose_after_answer_action,
    choose_planner_action,
    consistency_issues,
    initial_candidate_state,
    update_interview_plan,
    validate_evidence_extraction,
    validate_rubric_score,
)
from api.apps.services.cs_interview.replay import replay_planner_decision

SNAPSHOT = normalize_competency_snapshot("go_backend")


def _plan_item(requirement_id, topic, *, status="pending", attempts=0, jd_weight=0.3, must_have=False):
    return {
        "requirement_id": requirement_id,
        "topic_id": topic,
        "competency_id": topic,
        "must_have": must_have,
        "priority": 1.0,
        "jd_weight": jd_weight,
        "risk_multiplier": 1.4,
        "category_multiplier": 1.25,
        "focus_multiplier": 1.0,
        "objective": f"verify {requirement_id}",
        "preferred_question_type": "theory",
        "target_difficulty": "medium",
        "verification_strategy": "verify_jd_requirement",
        "status": status,
        "attempt_count": attempts,
    }


def _extraction_with_spans(answer="Sending to a closed channel panics"):
    return {
        "answer_spans": [{"span_id": "s1", "text": "Sending to a closed channel panics"}],
        "technical_claims": [{"claim_id": "c1", "text": "closed channel send panics", "span_ids": ["s1"], "topic_ids": ["go.runtime"]}],
        "decisions": [],
        "mechanisms": [],
        "tradeoffs": [],
        "examples": [],
        "contradictions": [],
        "uncertainty_phrases": [],
        "matched_indicators": [{"indicator": "核心概念与典型实现", "anchor_level": 2, "span_ids": ["s1"]}],
        "missing_indicators": [{"indicator": "机制解释与场景权衡", "anchor_level": 3}],
        "newly_claimed_facts": [],
        "project_facts": [],
        "covered_rubric_points": [],
        "unverified_boundaries": [],
        "deep_dive_branches": [],
    }


def _scorer(score=2, spans=("s1",), confidence=0.8, **overrides):
    return {
        "score": score,
        "matched_anchor": score,
        "verdict": "wrong_or_blank" if score <= 1 else "partial" if score <= 3 else "excellent",
        "matched_indicators": [],
        "missing_indicators": [],
        "evidence_span_ids": list(spans),
        "confidence": confidence,
        "needs_followup": False,
        "followup_focus": "",
        "weak_point": "",
        "feedback": "ok",
        "evaluation_summary": "ok",
        "factual_errors": [],
        **overrides,
    }


# --- 1. CompetencySpec and rubric validation ---------------------------------


def test_every_competency_has_valid_spec_and_complete_0_4_anchors():
    assert sorted(COMPETENCY_CATALOG) == sorted(build_competency_catalog())
    for role, specs in COMPETENCY_CATALOG.items():
        assert specs, role
        for spec in specs:
            assert validate_competency_spec(spec) == [], spec.competency_id
            assert [anchor.level for anchor in spec.score_anchors] == [0, 1, 2, 3, 4]
            assert len({anchor.observable_behavior for anchor in spec.score_anchors}) == 5
            assert validate_rubric_snapshot(build_rubric_snapshot(spec)) == []
    snapshot = normalize_competency_snapshot("go_backend")
    for competency in snapshot["competencies"]:
        assert sorted(map(int, competency["score_anchors"])) == [0, 1, 2, 3, 4]
        assert competency["score_anchors"]["0"]["observable_behavior"]
        assert competency["score_anchors"]["4"]["observable_behavior"]


def test_every_must_have_competency_has_a_manifest_backed_anchor_question():
    manifest_path = Path(__file__).resolve().parents[4] / "test" / "fixtures" / "cs_interview" / "public_eval" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata_by_question = {
        item["metadata"]["question_id"]: item["metadata"]
        for dataset in manifest["datasets"].values()
        for item in dataset["documents"]
    }
    for role in COMPETENCY_CATALOG:
        snapshot = normalize_competency_snapshot(role, "mid")
        groups = snapshot["anchor_groups"]
        for competency in snapshot["competencies"]:
            if not competency["must_have"]:
                continue
            group = next(group for group in groups.values() if group["competency_id"] == competency["competency_id"])
            assert group["question_ids"]
            for question_id in group["question_ids"]:
                assert metadata_by_question[question_id]["anchor_group_id"] == group["anchor_group_id"]


def test_score_anchor_validation_rejects_incomplete_or_vague_rubric():
    from api.apps.services.cs_interview.competencies import ScoreAnchor

    incomplete = validate_score_anchors(tuple(ScoreAnchor(level, f"L{level}", f"behavior {level}", (f"ind{level}",)) for level in (0, 1, 2, 3)))
    assert any("exactly levels 0,1,2,3,4" in error for error in incomplete)
    duplicated = validate_score_anchors(
        tuple(
            ScoreAnchor(level, f"L{level}", "identical vague behavior", ("ind",))
            for level in range(5)
        )
    )
    assert any("duplicates another level" in error for error in duplicated)


# --- 2. Evidence spans must come from the answer -----------------------------


def test_evidence_span_must_be_exact_answer_quote():
    raw = _extraction_with_spans()
    raw["answer_spans"] = [{"span_id": "s1", "text": "Sending to a closed channel panics"}, {"span_id": "s2", "text": "this is not in the answer"}]
    extraction = validate_evidence_extraction(raw, "Sending to a closed channel panics")
    assert [item["span_id"] for item in extraction.answer_spans] == ["s1"]
    assert all(item["text"] in "Sending to a closed channel panics" for item in extraction.answer_spans)


def test_evidence_claims_referencing_missing_spans_are_dropped():
    raw = _extraction_with_spans()
    raw["technical_claims"] = [{"claim_id": "c1", "text": "claim", "span_ids": ["missing"], "topic_ids": []}]
    extraction = validate_evidence_extraction(raw, "Sending to a closed channel panics")
    assert extraction.technical_claims == []


# --- 3. High score without evidence is rejected ------------------------------


def test_high_score_requires_evidence_span():
    extraction = validate_evidence_extraction(_extraction_with_spans(), "Sending to a closed channel panics")
    with pytest.raises(DomainError, match="high score requires at least one real evidence span"):
        validate_rubric_score(_scorer(score=4, spans=()), extraction, followup_count=0, max_followups=2)
    issues = consistency_issues(RubricScore(**_scorer(score=3, spans=())), extraction, code_result=None)
    assert any("high score lacks supporting answer evidence" in issue for issue in issues)
    assert any("score 2+ must cite" in issue for issue in issues)


def test_score_must_equal_matched_anchor_and_verdict():
    extraction = validate_evidence_extraction(_extraction_with_spans(), "Sending to a closed channel panics")
    with pytest.raises(DomainError, match="matched_anchor must equal"):
        validate_rubric_score(_scorer(score=2, matched_anchor=3), extraction, followup_count=0, max_followups=2)
    with pytest.raises(DomainError, match="inconsistent"):
        validate_rubric_score(_scorer(score=4, verdict="partial"), extraction, followup_count=0, max_followups=2)


# --- 4. Code result conflict is rejected -------------------------------------


def test_code_result_conflict_is_detected():
    extraction = validate_evidence_extraction(_extraction_with_spans(), "Sending to a closed channel panics")
    all_passed = {"status": "completed", "passed_count": 3, "total_count": 3}
    issues = consistency_issues(RubricScore(**_scorer(score=1, spans=("s1",))), extraction, code_result=all_passed)
    assert any("all code tests passed but the answer scores 0 or 1" in issue for issue in issues)
    failed = {"status": "compile_error", "passed_count": 0, "total_count": 3}
    issues = consistency_issues(RubricScore(**_scorer(score=4, spans=("s1",))), extraction, code_result=failed)
    assert any("code did not pass but the answer scores 4" in issue for issue in issues)


# --- 5. Planner must-have anchor coverage ------------------------------------


def test_planner_marks_unanchored_must_have_question_as_anchor():
    plan = [
        _plan_item("req-go", "go.runtime", jd_weight=0.6, must_have=True),
        _plan_item("req-mysql", "database.mysql", jd_weight=0.4),
    ]
    action = choose_planner_action(
        plan,
        initial_candidate_state(),
        [],
        remaining_question_budget=2,
        current_difficulty="medium",
        competency_snapshot=SNAPSHOT,
    )
    assert action.question_kind == "anchor"
    assert action.anchor_group_id.startswith("anchor-go_backend-go-runtime")
    assert action.competency_id == "go.runtime"
    assert action.expected_evidence.get("rubric_version")
    assert action.action_factors  # factor breakdown is persisted for replay
    for key in ("jd_weight", "verification_uncertainty", "expected_information_gain", "resume_risk", "repetition_penalty", "time_cost", "comparability_penalty", "action_value"):
        assert key in action.action_factors


def test_planner_does_not_skip_unanchored_must_have_even_when_low_risk():
    plan = [
        _plan_item("req-go", "go.runtime", jd_weight=0.1, must_have=True),
        _plan_item("req-mysql", "database.mysql", jd_weight=0.9, status="partial", attempts=1),
    ]
    action = choose_planner_action(
        plan,
        initial_candidate_state(),
        [],
        remaining_question_budget=1,
        current_difficulty="medium",
        competency_snapshot=SNAPSHOT,
    )
    assert action.competency_id == "go.runtime"
    assert action.question_kind == "anchor"


def test_low_confidence_or_failed_anchor_does_not_complete_the_baseline():
    plan = [_plan_item("req-go", "go.runtime", jd_weight=0.6, must_have=True)]
    rounds = [
        {
            "status": "completed",
            "topic": "go.runtime",
            "competency_id": "go.runtime",
            "question_kind": "anchor",
            "score": 2,
            "judge_confidence": 0.9,
            "evidence_evaluation": {},
        }
    ]
    action = choose_planner_action(
        plan,
        initial_candidate_state(),
        rounds,
        remaining_question_budget=1,
        current_difficulty="medium",
        competency_snapshot=SNAPSHOT,
    )
    assert action.question_kind == "anchor"
    assert action.competency_id == "go.runtime"


def test_planner_action_is_deterministic_for_identical_input():
    plan = [_plan_item("req-go", "go.runtime", jd_weight=0.6, must_have=True), _plan_item("req-mysql", "database.mysql", jd_weight=0.4)]
    kwargs = {"remaining_question_budget": 2, "current_difficulty": "medium", "competency_snapshot": SNAPSHOT}
    first = asdict(choose_planner_action(plan, initial_candidate_state(), [], **kwargs))
    second = asdict(choose_planner_action(plan, initial_candidate_state(), [], **kwargs))
    assert first == second
    assert first["selected_action"] == second["selected_action"]
    assert first["action_factors"] == second["action_factors"]


# --- 6. Adaptive follow-up preserves the anchor competency -------------------


def test_adaptive_followup_keeps_competency_and_kind():
    plan = [_plan_item("req-go", "go.runtime", jd_weight=0.6, must_have=True)]
    answer_state = {
        "contradictions": [
            {"contradiction_id": "ctd-x", "statement": "说过会用 channel", "conflicts_with": "简历", "topic_ids": ["go.runtime"], "evidence_span": "说过会用 channel", "confidence": 0.8, "status": "unresolved"}
        ],
        "newly_claimed_facts": [],
    }
    round_data = {"topic": "go.runtime", "competency_id": "go.runtime", "target_requirement_id": "req-go", "followup_count": 0, "question_type": "theory", "question_kind": "anchor"}
    action = choose_after_answer_action(
        plan,
        initial_candidate_state(),
        answer_state,
        None,
        round_data,
        [],
        remaining_question_budget=2,
        max_followups=2,
        current_difficulty="medium",
        competency_snapshot=SNAPSHOT,
    )
    assert action.selected_action == "resolve_contradiction"
    assert action.question_kind == "adaptive"
    assert action.competency_id == "go.runtime"


# --- 7. Uncovered / insufficient status --------------------------------------


def test_competency_verification_reports_uncovered_without_a_score():
    verification = build_competency_verification(SNAPSHOT, [])
    by_id = {item["competency_id"]: item for item in verification}
    assert by_id["go.runtime"]["status"] == "uncovered"
    assert by_id["go.runtime"]["score"] is None
    assert by_id["go.runtime"]["best_score"] is None


def test_low_confidence_round_is_insufficient_evidence_not_a_definitive_score():
    round_row = {
        "id": "r1",
        "status": "completed",
        "topic": "go.runtime",
        "competency_id": "go.runtime",
        "question_kind": "anchor",
        "score": 1,
        "judge_confidence": 0.3,
        "evidence_evaluation": {"evaluations": [{"evaluation": {"low_confidence": True, "scorer": {"evidence_span_ids": ["s1"]}, "extraction": {"answer_spans": [{"span_id": "s1", "text": "x"}], "contradictions": []}}}]},
    }
    verification = build_competency_verification(SNAPSHOT, [round_row])
    entry = next(item for item in verification if item["competency_id"] == "go.runtime")
    assert entry["status"] == "insufficient_evidence"
    assert entry["low_confidence"] is True


def test_verified_competency_matches_round_evidence():
    round_row = {
        "id": "r1",
        "status": "completed",
        "topic": "go.runtime",
        "competency_id": "go.runtime",
        "question_kind": "anchor",
        "score": 4,
        "judge_confidence": 0.9,
        "target_requirement_id": "req-go",
        "target_requirement": {"text": "熟悉 Go 并发"},
        "question_text": "解释关闭 channel 的语义",
        "evidence_evaluation": {"evaluations": [{"evaluation": {"low_confidence": False, "scorer": {"evidence_span_ids": ["s1"]}, "extraction": {"answer_spans": [{"span_id": "s1", "text": "发送 panic"}], "contradictions": []}}}]},
    }
    verification = build_competency_verification(SNAPSHOT, [round_row], job_snapshot={"extraction": {"requirements": []}})
    entry = next(item for item in verification if item["competency_id"] == "go.runtime")
    assert entry["status"] == "verified"
    assert entry["score"] == 4
    kinds = [item["kind"] for item in entry["evidence_track"]]
    assert "anchor_question" in kinds
    assert "answer_evidence" in kinds
    assert any(item["kind"] == "answer_evidence" and item["spans"] for item in entry["evidence_track"])


def test_level_policy_changes_required_score_without_redefining_score_scale():
    junior = normalize_competency_snapshot("go_backend", "junior")
    senior = normalize_competency_snapshot("go_backend", "senior")
    assert junior["role_policy"]["required_score"] == 2
    assert junior["role_policy"]["default_difficulty"] == "beginner"
    assert senior["role_policy"]["required_score"] == 4
    assert senior["role_policy"]["minimum_high_confidence_evidence"] == 1
    assert senior["role_policy"]["default_difficulty"] == "advanced"
    assert junior["rubrics"]["go.runtime"]["score_anchors"] == senior["rubrics"]["go.runtime"]["score_anchors"]
    plan = [_plan_item("req-go", "go.runtime", must_have=True)]
    assert update_interview_plan(plan, "req-go", score=3, completed=True, required_score=4)[0]["status"] == "partial"


# --- 8. Replay works with the new snapshot -----------------------------------


def test_replay_planner_decision_uses_competency_snapshot_deterministically():
    plan = [_plan_item("req-go", "go.runtime", jd_weight=0.6, must_have=True)]
    stored = asdict(choose_planner_action(plan, initial_candidate_state(), [], remaining_question_budget=2, current_difficulty="medium", competency_snapshot=SNAPSHOT))
    result = replay_planner_decision(
        planner_version="cs-interview-planner-v2",
        plan=plan,
        candidate_state=initial_candidate_state(),
        history=[],
        stored_action=stored,
        remaining_question_budget=2,
        current_difficulty="medium",
        competency_snapshot=SNAPSHOT,
    )
    assert result["outcome"] == "deterministic"


# --- 9. Report aggregates consistently with round evidence -------------------


def test_report_competency_verification_matches_round_scores():
    round_row = {
        "id": "r1",
        "status": "completed",
        "topic": "go.runtime",
        "competency_id": "go.runtime",
        "question_kind": "anchor",
        "score": 3,
        "judge_confidence": 0.8,
        "initial_score": 2,
        "followup_count": 1,
        "difficulty": "medium",
        "category": "baguwen",
        "question_type": "theory",
        "evidence_evaluation": {"evaluations": [{"evaluation": {"low_confidence": False, "scorer": {"evidence_span_ids": []}, "extraction": {"answer_spans": [], "contradictions": []}}}]},
    }
    report = build_report([round_row], {"initial_difficulty": "medium"}, competency_snapshot=SNAPSHOT, candidate_state=initial_candidate_state())
    entry = next(item for item in report["competency_verification"] if item["competency_id"] == "go.runtime")
    assert entry["status"] == "verified"
    assert entry["score"] == 3
    assert report["metrics"]["question_count"] == 1
