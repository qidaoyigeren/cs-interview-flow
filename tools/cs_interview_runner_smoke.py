"""Smoke-test successful Python/Go execution and runner network isolation.

This script deliberately uses only the Python standard library so it can run
against a freshly built runner image before the RAGFlow Python environment is
installed.
"""

from __future__ import annotations

import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

CASES = (
    (
        "python",
        "python",
        "import sys,json\nvalues=json.loads(sys.stdin.readline())\nprint(json.dumps(sum(values)))\n",
        [{"input": [1, 2, 3], "expected": 6}],
    ),
    (
        "go",
        "go",
        'package main\nimport ("encoding/json"; "fmt"; "os")\nfunc main(){var values []int; json.NewDecoder(os.Stdin).Decode(&values); total:=0; for _,value:=range values{total+=value}; fmt.Println(total)}\n',
        [{"input": [1, 2, 3], "expected": 6}],
    ),
    (
        "javascript",
        "javascript",
        "const values=JSON.parse(require('fs').readFileSync(0,'utf8')); console.log(JSON.stringify(values.reduce((a,b)=>a+b,0)));\n",
        [{"input": [1, 2, 3], "expected": 6}],
    ),
    (
        "network_isolation",
        "python",
        "import json,socket\nsock=socket.socket(); sock.settimeout(0.5)\ntry:\n sock.connect(('1.1.1.1',53)); print(json.dumps('connected'))\nexcept Exception:\n print(json.dumps('blocked'))\n",
        [{"input": None, "expected": "blocked"}],
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://cs-interview-runner:9390")
    parser.add_argument("--memory-mb", type=int, default=128)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    health = _request("GET", f"{base_url}/healthz", timeout=3)
    readiness = _request("GET", f"{base_url}/readyz", timeout=5)

    results = []
    for name, language, source_code, tests in CASES:
        payload = _request(
            "POST",
            f"{base_url}/v1/execute",
            payload={
                "execution_id": f"smoke-{name}",
                "language": language,
                "source_code": source_code,
                "tests": tests,
                "limits": {
                    "wall_time_ms": 8_000,
                    "cpu_time_ms": 3_000,
                    "memory_mb": args.memory_mb,
                    "processes": 16,
                    "output_bytes": 8_192,
                },
            },
            timeout=12,
        )
        results.append(
            {
                "case": name,
                "status": payload.get("status"),
                "passed_count": payload.get("passed_count"),
                "total_count": payload.get("total_count"),
                "runtime_ms": payload.get("runtime_ms"),
                "compiler_output": str(payload.get("compiler_output") or "")[:500],
            }
        )

    passed = all(row["status"] == "completed" and row["passed_count"] == row["total_count"] for row in results)
    passed = passed and readiness.get("status") == "ready" and readiness.get("self_test") == "sandbox_ok"
    print(
        json.dumps(
            {"passed": passed, "health": health, "readiness": readiness, "results": results},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if passed else 3


def _request(method: str, url: str, *, payload: dict | None = None, timeout: float) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
