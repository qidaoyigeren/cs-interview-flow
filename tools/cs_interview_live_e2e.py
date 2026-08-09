"""Run one real resume-grounded CS interview through RAGFlow, LLM, and SSE."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import requests

FORBIDDEN_PUBLIC_KEYS = {
    "reference_answer",
    "evaluation_rubric",
    "hidden_tests",
    "judge_prompt",
    "retrieval_evidence",
    "planner_actions",
    "answer_state",
    "supporting_state",
}

SCENARIOS: dict[str, dict[str, Any]] = {
    "go_runtime": {
        "resume": "test/fixtures/cs_interview/public_eval/resumes/anonymous_go_candidate.md",
        "job": "test/fixtures/cs_interview/public_eval/jobs/go_backend_intern.md",
        "profile_name": "公开语料 E2E - Go 后端",
        "role": "go_backend",
        "topic": "go.runtime",
        "difficulty": "medium",
        "category": "interview_experience",
        "weak_answer": "我会先把接口超时和 channel 缓冲调大，再观察 goroutine 数量是否下降。",
        "strong_answer": (
            "我会先用 runtime/pprof 的 goroutine profile、trace 和按版本对比的 goroutine 指标确认泄漏栈，"
            "重点检查请求返回后仍阻塞的 channel send、未停止的 ticker 和没有退出条件的重试。"
            "请求 context 要传到每个下游和 worker；worker 在 select 中同时监听结果发送与 ctx.Done，"
            "这样主请求取消后不会因为无人接收结果而永久阻塞。WithTimeout 返回的 cancel 仍要 defer 调用，"
            "以释放 timer 和父子引用。channel 由唯一发送方负责关闭，不能让多个接收方竞争关闭。"
            "并发入口还要用有界 worker 或 semaphore 限制放大。修复后以稳定压测验证 goroutine 回到基线，"
            "同时观察超时率、下游在途请求和内存曲线，而不是只把缓冲调大。"
        ),
    },
    "ai_backend_rag": {
        "resume": "test/fixtures/cs_interview/public_eval/resumes/ragflow_project_candidate.md",
        "job": "test/fixtures/cs_interview/public_eval/jobs/ai_backend_rag_intern.md",
        "profile_name": "公开语料 E2E - 大模型应用后端",
        "role": "ai_backend",
        "topic": "ai.rag",
        "difficulty": "advanced",
        "category": "interview_experience",
        "weak_answer": "我会把 top-k 调大，再换一个更大的生成模型，看看回答是否恢复。",
        "strong_answer": (
            "我会先把查询改写、embedding、关键词与向量召回、元数据过滤、重排、上下文构建和生成分段打点，"
            "比较升级前后的 P50/P95、候选数和超时率。用冻结评测集同时回放 Recall@K、MRR/NDCG、"
            "引用精确性、陈述到证据的蕴含率和端到端任务完成率，不能只看回答流畅度。"
            "接着检查 embedding 与索引版本是否一致、过滤是否误杀、top-k 和重排候选是否膨胀，"
            "并逐条验证最终结论能否由引用片段推出。优化时给各阶段设置超时预算，能并行的检索并行，"
            "对安全的查询与向量做缓存，并在评测护栏下截断候选；重排超时时采用有指标的降级而不是静默跳过。"
            "最后小流量灰度，对质量、延迟和成本设回滚阈值。"
        ),
    },
}


class E2EError(RuntimeError):
    pass


class Client:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/") + "/api/v1"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})

    def json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(method, self.base_url + path, timeout=180, **kwargs)
        try:
            payload = response.json()
        except ValueError as exc:
            raise E2EError(f"{method} {path} returned non-JSON HTTP {response.status_code}") from exc
        if not response.ok or payload.get("code") != 0:
            error_type = (payload.get("error") or {}).get("type")
            raise E2EError(f"{method} {path} failed: HTTP {response.status_code}, type={error_type}, message={payload.get('message', '')}")
        return payload.get("data")

    def sse(self, method: str, path: str, **kwargs: Any) -> tuple[float, list[dict[str, Any]]]:
        start = time.perf_counter()
        response = self.session.request(method, self.base_url + path, timeout=240, **kwargs)
        latency_ms = (time.perf_counter() - start) * 1000
        if not response.ok:
            raise E2EError(f"{method} {path} returned HTTP {response.status_code}: {response.text[:500]}")
        events: list[dict[str, Any]] = []
        event_name = "message"
        for line in response.text.splitlines():
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
                events.append({"event": event_name, "data": data})
        errors = [event for event in events if event["event"] == "error"]
        if errors:
            raise E2EError(f"SSE {path} failed: {errors[-1]['data']}")
        if not events:
            raise E2EError(f"SSE {path} returned no events")
        return latency_ms, events


def contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_PUBLIC_KEYS & set(value)) or any(contains_forbidden_key(item) for item in value.values())
    if isinstance(value, list):
        return any(contains_forbidden_key(item) for item in value)
    return False


def find_event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((event["data"] for event in events if event["event"] == name), None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="go_runtime")
    parser.add_argument("--resume", help="Override the scenario's resume fixture.")
    parser.add_argument("--job", help="Override the scenario's JD fixture.")
    parser.add_argument("--force-extraction", action="store_true")
    parser.add_argument("--base-url", default=os.getenv("RAGFLOW_BASE_URL", "http://localhost"))
    parser.add_argument("--api-key-env", default="RAGFLOW_API_KEY")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    scenario = SCENARIOS[args.scenario]
    api_key = os.getenv(args.api_key_env, "").strip()
    if not api_key:
        raise E2EError(f"Environment variable {args.api_key_env} is required")
    client = Client(args.base_url, api_key)
    resume_path = Path(args.resume or scenario["resume"]).resolve()
    upload_name = resume_path.stem + ".txt"

    config = client.json("GET", "/cs-interview/knowledge-config")
    if not config:
        raise E2EError("No active CS interview knowledge config")

    existing_resumes = client.json("GET", "/cs-interview/resumes") or []
    resume = next((row for row in existing_resumes if row.get("file_name") == upload_name), None)
    if resume is None:
        with resume_path.open("rb") as source:
            resume = client.json(
                "POST",
                "/cs-interview/resumes",
                files={"file": (upload_name, source, "text/plain; charset=utf-8")},
            )
    extraction_ms = 0.0
    if not resume.get("extraction") or args.force_extraction:
        start = time.perf_counter()
        resume = client.json(
            "POST",
            f"/cs-interview/resumes/{resume['id']}/extract",
            json={"force": bool(args.force_extraction)},
        )
        extraction_ms = (time.perf_counter() - start) * 1000
    extraction = resume.get("extraction") or {}

    job_path = Path(args.job or scenario["job"]).resolve()
    job_name = f"{scenario['profile_name']} JD"
    existing_jobs = client.json("GET", "/cs-interview/jobs") or []
    job = next((row for row in existing_jobs if row.get("name") == job_name), None)
    if job is None:
        job = client.json(
            "POST",
            "/cs-interview/jobs",
            json={
                "name": job_name,
                "source_type": "paste",
                "source_text": job_path.read_text(encoding="utf-8"),
            },
        )
    job_extraction_ms = 0.0
    if not job.get("extraction") or args.force_extraction:
        start = time.perf_counter()
        job = client.json(
            "POST",
            f"/cs-interview/jobs/{job['id']}/extract",
            json={"force": bool(args.force_extraction)},
        )
        job_extraction_ms = (time.perf_counter() - start) * 1000
    job_extraction = job.get("extraction") or {}

    profile = client.json(
        "POST",
        f"/cs-interview/resumes/{resume['id']}/profile",
        json={
            "name": scenario["profile_name"],
            "target_role": scenario["role"],
            "target_level": "mid",
            "focus_topics": [scenario["topic"]],
            "excluded_topics": [],
            "initial_difficulty": scenario["difficulty"],
            "preferred_categories": [scenario["category"]],
            "question_count": 1,
            "max_followups": 2,
            "job_id": job["id"],
        },
    )
    session = client.json(
        "POST",
        "/cs-interview/sessions",
        json={"profile_id": profile["id"], "knowledge_config_id": config["id"]},
    )

    start_ms, start_events = client.sse(
        "POST",
        f"/cs-interview/sessions/{session['id']}/start",
        json={"request_id": uuid.uuid4().hex, "state_version": session["state_version"]},
    )
    first_question = find_event(start_events, "next_question")
    if not first_question:
        raise E2EError("Interview start did not produce a question")
    state_version = int(first_question["session"]["state_version"])

    weak_answer = scenario["weak_answer"]
    weak_ms, weak_events = client.sse(
        "POST",
        f"/cs-interview/sessions/{session['id']}/answers",
        json={"request_id": uuid.uuid4().hex, "state_version": state_version, "answer": weak_answer},
    )
    followup = find_event(weak_events, "followup_question")
    if not followup:
        raise E2EError("The deliberately incomplete answer did not trigger a follow-up")
    state_version = int(followup["state_version"])

    strong_answer = scenario["strong_answer"]
    strong_ms, strong_events = client.sse(
        "POST",
        f"/cs-interview/sessions/{session['id']}/answers",
        json={"request_id": uuid.uuid4().hex, "state_version": state_version, "answer": strong_answer},
    )
    extra_followup = find_event(strong_events, "followup_question")
    if extra_followup:
        state_version = int(extra_followup["state_version"])
        retry_ms, retry_events = client.sse(
            "POST",
            f"/cs-interview/sessions/{session['id']}/answers",
            json={"request_id": uuid.uuid4().hex, "state_version": state_version, "answer": strong_answer},
        )
        strong_ms += retry_ms
        strong_events.extend(retry_events)

    final_session = client.json("GET", f"/cs-interview/sessions/{session['id']}")
    round_data = final_session["rounds"][0]
    passed_checks = {
        "resume_role_extracted": extraction.get("target_role") == scenario["role"],
        "jd_requirements_extracted": bool(job_extraction.get("requirements")),
        "question_grounded": bool(round_data.get("evidence_sources")),
        "question_targets_jd_requirement": bool(round_data.get("target_requirement_id")),
        "expected_topic": round_data.get("topic") == scenario["topic"],
        "expected_category": round_data.get("category") == scenario["category"],
        "adaptive_followup_triggered": int(round_data.get("followup_count") or 0) >= 1,
        "followup_limit_respected": int(round_data.get("followup_count") or 0) <= int(final_session["max_followups"]),
        "interview_completed": final_session.get("status") == "completed",
        "report_generated": bool(final_session.get("report")),
        "jd_matrix_generated": bool((final_session.get("report") or {}).get("jd_verification_matrix")),
        "no_hidden_fields_in_public_dto": not contains_forbidden_key(final_session),
    }
    report = final_session.get("report") or {}
    output = {
        "passed": all(passed_checks.values()),
        "scenario": args.scenario,
        "checks": passed_checks,
        "resume_extraction": {
            "target_role": extraction.get("target_role"),
            "target_level": extraction.get("target_level"),
            "technology_stack": extraction.get("technology_stack", []),
            "claimed_skill_count": len(extraction.get("claimed_skills") or []),
            "project_count": len(extraction.get("projects") or []),
        },
        "job_extraction": {
            "requirement_count": len(job_extraction.get("requirements") or []),
            "unmapped_requirement_count": len(job_extraction.get("unmapped_requirement_ids") or []),
        },
        "question": {
            "question_id": round_data.get("question_id"),
            "topic": round_data.get("topic"),
            "difficulty": round_data.get("difficulty"),
            "text": round_data.get("question_text"),
            "resume_probe": round_data.get("resume_probe"),
            "target_requirement": round_data.get("target_requirement"),
            "selected_action": round_data.get("selected_action"),
            "question_reason": round_data.get("question_reason"),
            "evidence_sources": round_data.get("evidence_sources"),
        },
        "interaction": {
            "followup_count": round_data.get("followup_count"),
            "followup_questions": round_data.get("followup_questions"),
            "initial_score": round_data.get("initial_score"),
            "final_score": round_data.get("score"),
            "verdict": round_data.get("verdict"),
            "feedback": round_data.get("feedback"),
        },
        "report": {
            "overall_score": report.get("overall_score"),
            "star_rating": report.get("star_rating"),
            "metrics": report.get("metrics"),
        },
        "latency_ms": {
            "resume_extraction": round(extraction_ms, 1),
            "job_extraction": round(job_extraction_ms, 1),
            "question_generation": round(start_ms, 1),
            "weak_answer_judge_and_followup": round(weak_ms, 1),
            "strong_answer_judge_and_report": round(strong_ms, 1),
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 0 if output["passed"] else 4


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, requests.RequestException, E2EError) as exc:
        print(json.dumps({"passed": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        raise SystemExit(1) from exc
