"""Apply candidate limits after bubblewrap created its user/PID namespaces."""

from __future__ import annotations

import json
import os
import resource
import sys


def main() -> None:
    config = json.loads(sys.argv[1])
    if sys.argv[2] != "--" or len(sys.argv) < 4:
        raise SystemExit(126)
    cpu_seconds = max(1, int(config["cpu_time_ms"]) // 1000)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    if config.get("address_space_mb") is not None:
        memory = int(config["address_space_mb"]) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    if config.get("processes") is not None:
        processes = int(config["processes"])
        resource.setrlimit(resource.RLIMIT_NPROC, (processes, processes))
    if config.get("file_bytes") is not None:
        maximum = int(config["file_bytes"])
        resource.setrlimit(resource.RLIMIT_FSIZE, (maximum, maximum))
    if config.get("open_files") is not None:
        maximum = int(config["open_files"])
        resource.setrlimit(resource.RLIMIT_NOFILE, (maximum, maximum))
    os.execvpe(sys.argv[3], sys.argv[3:], os.environ)


if __name__ == "__main__":
    main()
