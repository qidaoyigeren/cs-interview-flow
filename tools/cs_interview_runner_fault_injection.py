"""Exercise runner timeout, memory, process, output, cancellation, and drain contracts.

Run this only against the isolated production runner container/Pod. It does not
need RAGFlow, a database, Redis, or an external LLM.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

TIMEOUT_SOURCES = {
    "python": "while True: pass\n",
    "go": 'package main\nfunc main(){for {}}\n',
    "javascript": "while (true) {}\n",
}
MEMORY_SOURCES = {
    "python": "x=bytearray(256*1024*1024)\nprint(1)\n",
    "go": 'package main\nimport "fmt"\nfunc main(){x:=make([]byte,768<<20); for i:=range x{x[i]=1}; fmt.Println(len(x))}\n',
    "javascript": "const x=new Array(32*1024*1024).fill(1); console.log(x.length);\n",
}
PROCESS_SOURCES = {
    "python": """import json,os,time
children=[]
blocked=False
for _ in range(64):
 try:
  pid=os.fork()
  if pid==0: time.sleep(2); os._exit(0)
  children.append(pid)
 except OSError: blocked=True; break
for pid in children:
 try: os.kill(pid, 9)
 except ProcessLookupError: pass
print(json.dumps(blocked))
""",
    "go": """package main
import("encoding/json";"os";"os/exec";"time")
func main(){if len(os.Args)>1{time.Sleep(2*time.Second);return}; blocked:=false; children:=[]*exec.Cmd{}; for i:=0;i<64;i++{c:=exec.Command(os.Args[0],"child"); if c.Start()!=nil{blocked=true;break}; children=append(children,c)}; for _,c:=range children{_ = c.Process.Kill()}; _=json.NewEncoder(os.Stdout).Encode(blocked)}
""",
    "javascript": """const {spawn}=require('child_process');
if(process.argv[2]==='child'){setTimeout(()=>{},2000)}else{let blocked=false;const children=[];for(let i=0;i<64;i++){try{const c=spawn(process.execPath,[__filename,'child']);children.push(c);c.on('error',()=>{blocked=true})}catch(_){blocked=true;break}}setTimeout(()=>{for(const c of children){try{c.kill('SIGKILL')}catch(_){}}console.log(JSON.stringify(blocked||children.length<64))},300)}
""",
}
OUTPUT_SOURCES = {
    "python": "print('x'*1000000)\n",
    "go": 'package main\nimport("fmt";"strings")\nfunc main(){fmt.Print(strings.Repeat("x",1000000))}\n',
    "javascript": "console.log('x'.repeat(1000000));\n",
}


def request(method: str, url: str, *, payload: dict | None = None, timeout: float = 15) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url, data=body, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def execute(base_url: str, name: str, language: str, source: str, *, wall_ms: int, memory_mb: int = 64, processes: int = 8):
    return request(
        "POST",
        f"{base_url}/v1/execute",
        payload={
            "execution_id": name,
            "language": language,
            "source_code": source,
            "tests": [{"input": None, "expected": "never_matches"}],
            "limits": {
                "wall_time_ms": wall_ms,
                "cpu_time_ms": min(wall_ms, 1000),
                "memory_mb": memory_mb,
                "processes": processes,
                "output_bytes": 1024,
            },
        },
        timeout=max(15, wall_ms / 1000 + 8),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:19390")
    parser.add_argument("--drain", action="store_true", help="Also verify readiness and admission after drain.")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    status, readiness = request("GET", f"{base_url}/readyz", timeout=5)
    checks: list[dict] = [{"case": "sandbox_self_test", "passed": status == 200 and readiness.get("self_test") == "sandbox_ok"}]

    for language, source in TIMEOUT_SOURCES.items():
        http, result = execute(base_url, f"timeout-{language}", language, source, wall_ms=500)
        checks.append({"case": f"timeout_{language}", "passed": http == 200 and result.get("status") == "timeout", "result": result.get("status")})

    for language, source in MEMORY_SOURCES.items():
        http, result = execute(base_url, f"memory-{language}", language, source, wall_ms=3500)
        checks.append({"case": f"memory_{language}", "passed": http == 200 and result.get("status") in {"runtime_error", "timeout"}, "result": result.get("status")})

    for language, source in PROCESS_SOURCES.items():
        http, result = execute(base_url, f"process-{language}", language, source, wall_ms=3500, processes=8)
        test_result = (result.get("test_results") or [{}])[0]
        checks.append(
            {
                "case": f"process_{language}",
                "passed": http == 200 and (test_result.get("actual") is True or result.get("status") in {"runtime_error", "timeout"}),
                "result": result.get("status"),
            }
        )

    for language, source in OUTPUT_SOURCES.items():
        http, result = execute(base_url, f"output-{language}", language, source, wall_ms=2500)
        test_result = (result.get("test_results") or [{}])[0]
        serialized = json.dumps(result)
        checks.append(
            {
                "case": f"output_{language}",
                "passed": http == 200 and bool(test_result.get("output_truncated")) and len(serialized) < 10_000,
                "result": result.get("status"),
            }
        )

    cancellation_result: dict = {}

    def run_cancellable():
        cancellation_result["execute"] = execute(
            base_url, "cancel-python", "python", TIMEOUT_SOURCES["python"], wall_ms=8_000
        )

    thread = threading.Thread(target=run_cancellable)
    thread.start()
    time.sleep(0.4)
    cancel_http, cancel_payload = request("DELETE", f"{base_url}/v1/executions/cancel-python", timeout=3)
    thread.join(timeout=10)
    execute_result = cancellation_result.get("execute", (0, {}))[1]
    checks.append(
        {
            "case": "cancel_process_group",
            "passed": cancel_http == 200 and cancel_payload.get("cancelled") is True and not thread.is_alive() and execute_result.get("status") != "completed",
            "result": execute_result.get("status"),
        }
    )

    if args.drain:
        drain_http, _ = request("POST", f"{base_url}/drain", payload={}, timeout=3)
        ready_http, _ = request("GET", f"{base_url}/readyz", timeout=3)
        execute_http, _ = execute(base_url, "after-drain", "python", "print(1)", wall_ms=500)
        checks.append({"case": "drain_readiness_and_admission", "passed": drain_http == 200 and ready_http == 503 and execute_http == 503})

    passed = all(check["passed"] for check in checks)
    print(json.dumps({"passed": passed, "checks": checks}, indent=2))
    return 0 if passed else 4


if __name__ == "__main__":
    raise SystemExit(main())
