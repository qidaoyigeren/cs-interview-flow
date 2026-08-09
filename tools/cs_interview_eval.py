"""Run the deterministic CS interview offline evaluation fixture."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def _load_evaluator():
    """Load the pure evaluator without booting the Quart application package."""

    package_names = ("api", "api.apps", "api.apps.services", "api.apps.services.cs_interview")
    for package_name in package_names:
        package = sys.modules.setdefault(package_name, types.ModuleType(package_name))
        package.__path__ = []

    base = REPOSITORY_ROOT / "api" / "apps" / "services" / "cs_interview"
    for module_name in ("domain", "replay", "evaluation"):
        qualified_name = f"api.apps.services.cs_interview.{module_name}"
        spec = importlib.util.spec_from_file_location(qualified_name, base / f"{module_name}.py")
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load {qualified_name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified_name] = module
        spec.loader.exec_module(module)
    return sys.modules["api.apps.services.cs_interview.evaluation"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate CS interview retrieval, judging, and reporting quality.")
    parser.add_argument(
        "--fixture",
        default="test/fixtures/cs_interview/offline_eval.json",
        help="Path to an original/synthetic evaluation fixture.",
    )
    parser.add_argument("--json-output", help="Optional path for the machine-readable result.")
    parser.add_argument(
        "--labeled",
        action="store_true",
        help="Also validate and summarize the human-labeled quality set (informational).",
    )
    parser.add_argument(
        "--record-run",
        action="store_true",
        help="Persist the run into interview_evaluation_run/metric when a DB is reachable.",
    )
    args = parser.parse_args()

    evaluator = _load_evaluator()
    result = evaluator.evaluate_file(args.fixture)
    payload = json.dumps(result.as_dict(), ensure_ascii=False, indent=2)
    if args.json_output:
        Path(args.json_output).write_text(payload + "\n", encoding="utf-8")
    print(evaluator.human_summary(result))
    if args.labeled:
        labeled_path = Path(args.fixture).with_name("labeled_quality.json")
        if labeled_path.exists():
            labeled = json.loads(labeled_path.read_text(encoding="utf-8"))
            print("Labeled quality set:", json.dumps(evaluator.labeled_stats(labeled), ensure_ascii=False))
    if args.record_run:
        try:
            from api.apps.services.cs_interview.eval_runs import persist_run

            run_id = persist_run(result, fixture_version=str(Path(args.fixture).resolve().name))
            print(f"recorded evaluation run: {run_id}")
        except Exception as exc:  # noqa: BLE001 - persistence is best effort from the CLI
            print(f"record-run skipped (no reachable DB): {type(exc).__name__}")
    print(payload)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
