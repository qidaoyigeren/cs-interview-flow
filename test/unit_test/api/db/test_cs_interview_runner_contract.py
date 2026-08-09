import importlib.util
import sys
import time
from pathlib import Path

import pytest


def _load_runner():
    path = Path(__file__).resolve().parents[4] / "docker" / "cs-interview-runner" / "runner.py"
    spec = importlib.util.spec_from_file_location("cs_interview_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_runner_validates_language_source_and_tests():
    runner = _load_runner()
    with pytest.raises(ValueError, match="unsupported_language"):
        runner.execute({"language": "bash", "source_code": "echo unsafe", "tests": [{"input": 1, "expected": 1}]})
    with pytest.raises(ValueError, match="invalid_tests"):
        runner.execute({"language": "python", "source_code": "print(1)", "tests": []})


def test_runner_reports_timeout_and_truncates_output(monkeypatch):
    runner = _load_runner()
    monkeypatch.setattr(
        runner,
        "run_process",
        lambda *_args, **_kwargs: {
            "exit_code": -9,
            "stdout": "",
            "stderr": "",
            "output_truncated": False,
            "timed_out": True,
            "runtime_ms": 100,
        },
    )
    result = runner.execute(
        {
            "language": "python",
            "source_code": "print(input())",
            "tests": [{"input": 1, "expected": 1}],
            "limits": {"wall_time_ms": 100},
        }
    )
    assert result["status"] == "timeout"
    assert result["passed_count"] == 0
    assert result["total_count"] == 1
    text, truncated = runner.truncate(b"a" * 20, 8)
    assert text == "a" * 8
    assert truncated


def test_go_compiler_uses_container_memory_cap_but_candidate_keeps_address_space_limit(monkeypatch):
    runner = _load_runner()
    calls = []

    def fake_run(*_args, **kwargs):
        calls.append(kwargs)
        return {
            "exit_code": 0,
            "stdout": "6\n" if len(calls) == 2 else "",
            "stderr": "",
            "output_truncated": False,
            "timed_out": False,
            "runtime_ms": 10,
        }

    monkeypatch.setattr(runner, "run_process", fake_run)
    result = runner.execute(
        {
            "language": "go",
            "source_code": 'package main\nimport "fmt"\nfunc main(){fmt.Println(6)}',
            "tests": [{"input": None, "expected": 6}],
        }
    )

    assert result["status"] == "completed"
    assert calls[0]["enforce_address_space"] is False
    assert calls[0]["enforce_process_limit"] is False
    assert calls[0]["enforce_file_limits"] is False
    assert calls[0]["go_cache"] == runner.SHARED_GO_CACHE
    assert calls[1].get("enforce_address_space", True) is True
    assert calls[1].get("enforce_process_limit", True) is True
    assert calls[1].get("enforce_file_limits", True) is True
    assert calls[1]["address_space_mb"] == 1024
    assert calls[1]["extra_env"] == {"GOMEMLIMIT": "128MiB"}


def test_javascript_uses_a_hard_address_space_backstop(monkeypatch):
    runner = _load_runner()
    calls = []

    def fake_run(*_args, **kwargs):
        calls.append(kwargs)
        return {
            "exit_code": 0,
            "stdout": "1\n",
            "stderr": "",
            "output_truncated": False,
            "timed_out": False,
            "runtime_ms": 10,
        }

    monkeypatch.setattr(runner, "run_process", fake_run)
    result = runner.execute(
        {
            "language": "javascript",
            "source_code": "console.log(1)",
            "tests": [{"input": None, "expected": 1}],
            "limits": {"memory_mb": 64},
        }
    )

    assert result["status"] == "completed"
    assert calls[0]["address_space_mb"] == 768
    assert calls[0]["extra_env"] == {"NODE_OPTIONS": "--max-old-space-size=32"}


def test_drain_invalidates_cached_readiness_immediately():
    runner = _load_runner()
    runner.READINESS_RESULT = (time.monotonic(), True, "sandbox_ok")
    runner.DRAINING.set()
    ready, detail = runner.sandbox_self_test(cache_seconds=30)
    assert not ready
    assert detail == "draining"
    runner.DRAINING.clear()


def test_go_cache_seed_copy_does_not_request_metadata_syscalls(monkeypatch, tmp_path):
    runner = _load_runner()
    source = tmp_path / "seed"
    target = tmp_path / "target"
    (source / "aa").mkdir(parents=True)
    (source / "aa" / "cache-entry").write_bytes(b"compiled")
    monkeypatch.setattr(runner, "GO_CACHE_SEED", source)
    monkeypatch.setattr(runner, "SHARED_GO_CACHE", target)
    monkeypatch.setattr(runner.shutil, "copytree", lambda *_args, **_kwargs: pytest.fail("copytree copies metadata"))

    runner.prepare_go_cache()

    assert (target / "aa" / "cache-entry").read_bytes() == b"compiled"
