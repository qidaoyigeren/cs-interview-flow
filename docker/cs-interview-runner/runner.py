"""Small HTTP service that executes submissions inside a nested OS sandbox.

This process is designed to run in its own locked-down container. Candidate
processes are additionally launched through bubblewrap with a new network
namespace and a read-only view of the container filesystem.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


MAX_REQUEST_BYTES = 256_000
LANGUAGES = {
    "python": {"filename": "solution.py", "compile": None, "run": ["/usr/bin/python3", "/work/solution.py"]},
    "go": {
        "filename": "solution.go",
        "compile": ["/usr/local/go/bin/go", "build", "-p=1", "-trimpath", "-o", "/work/solution", "/work/solution.go"],
        "run": ["/work/solution"],
    },
    "javascript": {"filename": "solution.js", "compile": None, "run": ["/usr/local/bin/node", "/work/solution.js"]},
}
GO_CACHE_SEED = Path("/opt/runner/go-cache-seed")
SHARED_GO_CACHE = Path("/tmp/cs-interview-go-cache")
EXECUTION_SLOT = threading.BoundedSemaphore(1)
ACTIVE_PROCESSES: dict[str, subprocess.Popen] = {}
ACTIVE_PROCESSES_LOCK = threading.Lock()
DRAINING = threading.Event()
READINESS_LOCK = threading.Lock()
READINESS_RESULT: tuple[float, bool, str] = (0.0, False, "not_checked")
EXECUTION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class Limits:
    wall_time_ms: int
    cpu_time_ms: int
    memory_mb: int
    processes: int
    output_bytes: int

    @classmethod
    def from_payload(cls, value: Any) -> "Limits":
        value = value if isinstance(value, dict) else {}
        return cls(
            wall_time_ms=max(100, min(int(value.get("wall_time_ms", 5000)), 10_000)),
            cpu_time_ms=max(100, min(int(value.get("cpu_time_ms", 3000)), 8_000)),
            memory_mb=max(32, min(int(value.get("memory_mb", 128)), 256)),
            processes=max(1, min(int(value.get("processes", 16)), 32)),
            output_bytes=max(512, min(int(value.get("output_bytes", 8192)), 32_768)),
        )


def truncate(value: bytes, maximum: int) -> tuple[str, bool]:
    truncated = len(value) > maximum
    return value[:maximum].decode("utf-8", errors="replace"), truncated


def normalize_actual(stdout: str) -> Any:
    value = stdout.strip()
    if not value:
        return ""
    try:
        return json.loads(value.splitlines()[-1])
    except json.JSONDecodeError:
        return value


def sandbox_command(workdir: Path, command: list[str], limit_config: dict[str, int | None], go_cache: Path | None = None) -> list[str]:
    command_prefix = [
        "/usr/bin/bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-user",
        "--unshare-pid",
        "--unshare-ipc",
        "--unshare-uts",
        "--unshare-cgroup",
        "--unshare-net",
        "--ro-bind",
        "/",
        "/",
        "--tmpfs",
        "/dev",
        "--dev-bind",
        "/dev/null",
        "/dev/null",
        "--dev-bind",
        "/dev/zero",
        "/dev/zero",
        "--dev-bind",
        "/dev/random",
        "/dev/random",
        "--dev-bind",
        "/dev/urandom",
        "/dev/urandom",
        "--symlink",
        "/proc/self/fd",
        "/dev/fd",
        "--symlink",
        "/proc/self/fd/0",
        "/dev/stdin",
        "--symlink",
        "/proc/self/fd/1",
        "/dev/stdout",
        "--symlink",
        "/proc/self/fd/2",
        "/dev/stderr",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",
        "--bind",
        str(workdir),
        "/work",
    ]
    if go_cache is not None:
        command_prefix.extend(["--bind", str(go_cache), "/work/.gocache"])
    return [
        *command_prefix,
        "--chdir",
        "/work",
        "--setenv",
        "HOME",
        "/tmp",
        "--setenv",
        "GOCACHE",
        "/work/.gocache",
        "--setenv",
        "GOMODCACHE",
        "/work/.gomodcache",
        "--",
        "/usr/bin/python3",
        "/opt/runner/limit_exec.py",
        json.dumps(limit_config, separators=(",", ":")),
        "--",
        *command,
    ]


def run_process(
    workdir: Path,
    command: list[str],
    limits: Limits,
    stdin: bytes = b"",
    *,
    enforce_address_space: bool = True,
    enforce_process_limit: bool = True,
    enforce_file_limits: bool = True,
    go_cache: Path | None = None,
    address_space_mb: int | None = None,
    extra_env: dict[str, str] | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        environment = {"PATH": "/usr/local/go/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "GOMAXPROCS": "2"}
        environment.update(extra_env or {})
        limit_config = {
            "cpu_time_ms": limits.cpu_time_ms,
            "address_space_mb": (address_space_mb or limits.memory_mb) if enforce_address_space else None,
            "processes": limits.processes if enforce_process_limit else None,
            "file_bytes": limits.output_bytes if enforce_file_limits else None,
            "open_files": 64 if enforce_file_limits else None,
        }
        process = subprocess.Popen(
            sandbox_command(workdir, command, limit_config, go_cache),
            stdin=subprocess.PIPE,
            stdout=stdout_file,
            stderr=stderr_file,
            env=environment,
            preexec_fn=os.setsid,
            close_fds=True,
        )
        if execution_id:
            with ACTIVE_PROCESSES_LOCK:
                ACTIVE_PROCESSES[execution_id] = process
        try:
            try:
                process.communicate(stdin, timeout=limits.wall_time_ms / 1000)
                timed_out = False
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
        finally:
            if execution_id:
                with ACTIVE_PROCESSES_LOCK:
                    if ACTIVE_PROCESSES.get(execution_id) is process:
                        ACTIVE_PROCESSES.pop(execution_id, None)
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(limits.output_bytes + 1)
        stderr = stderr_file.read(limits.output_bytes + 1)
    stdout_text, stdout_truncated = truncate(stdout, limits.output_bytes)
    stderr_text, stderr_truncated = truncate(stderr, limits.output_bytes)
    stdout_truncated = stdout_truncated or len(stdout) >= limits.output_bytes
    stderr_truncated = stderr_truncated or len(stderr) >= limits.output_bytes
    return {
        "exit_code": process.returncode,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "output_truncated": stdout_truncated or stderr_truncated,
        "timed_out": timed_out,
        "runtime_ms": int((time.perf_counter() - started) * 1000),
    }


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    execution_id = str(payload.get("execution_id") or "")
    language = str(payload.get("language", "")).lower()
    source = payload.get("source_code")
    tests = payload.get("tests")
    if language not in LANGUAGES:
        raise ValueError("unsupported_language")
    if execution_id and not EXECUTION_ID_PATTERN.fullmatch(execution_id):
        raise ValueError("invalid_execution_id")
    if not isinstance(source, str) or not source or len(source) > 50_000:
        raise ValueError("invalid_source")
    if not isinstance(tests, list) or not tests or len(tests) > 50:
        raise ValueError("invalid_tests")
    limits = Limits.from_payload(payload.get("limits"))
    language_config = LANGUAGES[language]
    deadline = time.monotonic() + limits.wall_time_ms / 1000

    def remaining_limits() -> Limits | None:
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            return None
        return replace(limits, wall_time_ms=min(limits.wall_time_ms, remaining_ms))

    with tempfile.TemporaryDirectory(prefix="cs-interview-") as temporary:
        workdir = Path(temporary)
        os.chmod(workdir, 0o700)
        (workdir / language_config["filename"]).write_text(source, encoding="utf-8")
        (workdir / ".gocache").mkdir()
        (workdir / ".gomodcache").mkdir()

        compile_command = language_config["compile"]
        if compile_command:
            compile_limits = remaining_limits()
            if compile_limits is None:
                return {
                    "status": "timeout",
                    "passed_count": 0,
                    "total_count": len(tests),
                    "runtime_ms": limits.wall_time_ms,
                    "memory_kb": 0,
                    "compiler_output": "Compilation timed out.",
                    "test_results": [],
                }
            # The Go compiler reserves a large virtual address range, starts more
            # helper threads, and writes cache/object files larger than candidate
            # output limits. Applying candidate RLIMITs here rejects valid code.
            # Compilation remains bounded by CPU/time plus runner container cgroup,
            # PID, read-only-root, and tmpfs caps. The compiled candidate is still
            # executed with every requested RLIMIT below.
            compiled = run_process(
                workdir,
                compile_command,
                compile_limits,
                enforce_address_space=False,
                enforce_process_limit=False,
                enforce_file_limits=False,
                go_cache=SHARED_GO_CACHE,
                execution_id=execution_id or None,
            )
            if compiled["timed_out"]:
                return {
                    "status": "timeout",
                    "passed_count": 0,
                    "total_count": len(tests),
                    "runtime_ms": compiled["runtime_ms"],
                    "memory_kb": 0,
                    "compiler_output": "Compilation timed out.",
                    "test_results": [],
                }
            if compiled["exit_code"] != 0:
                return {
                    "status": "compile_error",
                    "passed_count": 0,
                    "total_count": len(tests),
                    "runtime_ms": compiled["runtime_ms"],
                    "memory_kb": 0,
                    "compiler_output": compiled["stderr"],
                    "test_results": [],
                }

        results = []
        passed = 0
        runtime_ms = 0
        final_status = "completed"
        compiler_output = ""
        for index, case in enumerate(tests):
            if not isinstance(case, dict) or "input" not in case or "expected" not in case:
                raise ValueError("invalid_tests")
            case_limits = remaining_limits()
            if case_limits is None:
                final_status = "timeout"
                compiler_output = "Submission wall-time limit was exceeded."
                results.extend(
                    {
                        "index": pending,
                        "status": "timeout" if pending == index else "not_run",
                        "passed": False,
                        "actual": None,
                        "expected": tests[pending].get("expected") if isinstance(tests[pending], dict) else None,
                        "runtime_ms": 0,
                        "output_truncated": False,
                    }
                    for pending in range(index, len(tests))
                )
                break
            stdin = (json.dumps(case["input"], ensure_ascii=False) + "\n").encode("utf-8")
            runtime_env = None
            address_space_mb = None
            if language == "go":
                address_space_mb = 1024
                runtime_env = {"GOMEMLIMIT": f"{limits.memory_mb}MiB"}
            elif language == "javascript":
                # V8 needs roughly 600 MiB of virtual address space merely to
                # reserve its code range. 768 MiB is the measured minimum that
                # starts Node 22 while still making RLIMIT_AS a hard backstop;
                # the requested heap budget remains enforced by V8 below.
                address_space_mb = 768
                runtime_env = {"NODE_OPTIONS": f"--max-old-space-size={max(16, limits.memory_mb - 32)}"}
            run = run_process(
                workdir,
                language_config["run"],
                case_limits,
                stdin,
                address_space_mb=address_space_mb,
                extra_env=runtime_env,
                execution_id=execution_id or None,
            )
            runtime_ms += run["runtime_ms"]
            actual = normalize_actual(run["stdout"])
            case_passed = not run["timed_out"] and run["exit_code"] == 0 and actual == case["expected"]
            passed += int(case_passed)
            if run["timed_out"]:
                status = "timeout"
            elif run["exit_code"] != 0:
                status = "runtime_error"
            elif not case_passed:
                status = "wrong_answer"
            else:
                status = "passed"
            if status != "passed" and final_status == "completed":
                final_status = status
            if status in {"runtime_error", "timeout"} and not compiler_output:
                compiler_output = run["stderr"] or ("Execution timed out." if status == "timeout" else "Execution failed.")
            results.append(
                {
                    "index": index,
                    "status": status,
                    "passed": case_passed,
                    "actual": actual,
                    "expected": case["expected"],
                    "runtime_ms": run["runtime_ms"],
                    "output_truncated": run["output_truncated"],
                }
            )
        return {
            "status": final_status,
            "passed_count": passed,
            "total_count": len(tests),
            "runtime_ms": runtime_ms,
            "memory_kb": 0,
            "compiler_output": compiler_output,
            "test_results": results,
        }


def cancel_execution(execution_id: str) -> bool:
    if not EXECUTION_ID_PATTERN.fullmatch(execution_id):
        return False
    with ACTIVE_PROCESSES_LOCK:
        process = ACTIVE_PROCESSES.get(execution_id)
    if process is None:
        return False
    try:
        os.killpg(process.pid, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return False


def prepare_go_cache() -> None:
    """Seed the writable cache without copying metadata or extended attrs.

    ``shutil.copytree`` uses copystat/listxattr, which are unnecessary for Go
    cache contents and intentionally absent from the minimal seccomp profile.
    """

    SHARED_GO_CACHE.mkdir(parents=True, exist_ok=True)
    for source in GO_CACHE_SEED.rglob("*"):
        target = SHARED_GO_CACHE / source.relative_to(GO_CACHE_SEED)
        if source.is_dir():
            target.mkdir(exist_ok=True)
        elif source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)


def sandbox_self_test(*, cache_seconds: float = 30.0) -> tuple[bool, str]:
    """Execute a harmless command through the exact namespace/rlimit path."""

    global READINESS_RESULT
    # Drain must take effect immediately; a cached successful self-test must
    # never keep a terminating Pod in Service endpoints.
    if DRAINING.is_set():
        READINESS_RESULT = (time.monotonic(), False, "draining")
        return False, "draining"
    checked_at, ready, detail = READINESS_RESULT
    if time.monotonic() - checked_at < cache_seconds:
        return ready, detail
    with READINESS_LOCK:
        checked_at, ready, detail = READINESS_RESULT
        if time.monotonic() - checked_at < cache_seconds:
            return ready, detail
        if not shutil.which("bwrap"):
            READINESS_RESULT = (time.monotonic(), False, "bubblewrap_missing")
            return False, "bubblewrap_missing"
        try:
            with tempfile.TemporaryDirectory(prefix="cs-interview-self-test-") as temporary:
                workdir = Path(temporary)
                os.chmod(workdir, 0o700)
                (workdir / ".gocache").mkdir()
                (workdir / ".gomodcache").mkdir()
                result = run_process(
                    workdir,
                    ["/usr/bin/python3", "-c", "print(17)"],
                    Limits(1000, 500, 64, 4, 1024),
                )
            ready = not result["timed_out"] and result["exit_code"] == 0 and result["stdout"].strip() == "17"
            detail = "sandbox_ok" if ready else "sandbox_execution_failed"
        except Exception as exc:  # never expose syscall or host details through readiness
            ready = False
            detail = type(exc).__name__
        READINESS_RESULT = (time.monotonic(), ready, detail)
        return ready, detail


class Handler(BaseHTTPRequestHandler):
    server_version = "cs-interview-runner/1"

    def log_message(self, format: str, *args):
        # Do not log request bodies or candidate source code.
        print(f"runner {self.address_string()} {format % args}", flush=True)

    def _json(self, status: int, payload: dict[str, Any]):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/healthz":
            self._json(200, {"status": "alive", "draining": DRAINING.is_set()})
        elif self.path == "/readyz":
            ready, detail = sandbox_self_test()
            self._json(200 if ready else 503, {"status": "ready" if ready else "unavailable", "self_test": detail})
        elif self.path == "/drain":
            # Kubernetes lifecycle httpGet always uses GET.
            DRAINING.set()
            self._json(200, {"status": "draining"})
        else:
            self._json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path == "/drain":
            DRAINING.set()
            self._json(200, {"status": "draining"})
            return
        if self.path != "/v1/execute":
            self._json(404, {"error": "not_found"})
            return
        try:
            if DRAINING.is_set():
                self._json(503, {"error": "runner_draining"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("request_too_large")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("invalid_request")
            if not EXECUTION_SLOT.acquire(blocking=False):
                self._json(429, {"error": "runner_busy"})
                return
            try:
                self._json(200, execute(payload))
            finally:
                EXECUTION_SLOT.release()
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception as exc:
            self._json(500, {"error": type(exc).__name__})

    def do_DELETE(self):
        prefix = "/v1/executions/"
        if not self.path.startswith(prefix):
            self._json(404, {"error": "not_found"})
            return
        execution_id = self.path[len(prefix) :]
        cancelled = cancel_execution(execution_id)
        self._json(200 if cancelled else 404, {"cancelled": cancelled})


if __name__ == "__main__":
    prepare_go_cache()
    server = ThreadingHTTPServer(("0.0.0.0", 9390), Handler)
    server.daemon_threads = True

    def begin_shutdown(_signum, _frame):
        DRAINING.set()

        def finish_shutdown():
            deadline = time.monotonic() + float(os.getenv("RUNNER_DRAIN_SECONDS", "20"))
            while time.monotonic() < deadline:
                with ACTIVE_PROCESSES_LOCK:
                    if not ACTIVE_PROCESSES:
                        break
                time.sleep(0.1)
            with ACTIVE_PROCESSES_LOCK:
                execution_ids = list(ACTIVE_PROCESSES)
            for execution_id in execution_ids:
                cancel_execution(execution_id)
            server.shutdown()

        threading.Thread(target=finish_shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, begin_shutdown)
    signal.signal(signal.SIGINT, begin_shutdown)
    server.serve_forever()
