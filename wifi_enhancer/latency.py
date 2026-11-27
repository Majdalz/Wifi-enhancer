"""Latency / jitter / packet-loss test using the system ping command."""

from __future__ import annotations

import platform
import re
import shutil
import statistics
import subprocess
from typing import List

# Only fixed targets are allowed so user input never reaches the command line.
TARGETS = {
    "cloudflare": "1.1.1.1",
    "google": "8.8.8.8",
    "quad9": "9.9.9.9",
}


def parse_ping_times(output: str) -> List[float]:
    times = []
    for m in re.finditer(r"time\s*([=<])\s*([\d.]+)\s*ms", output, re.I):
        val = float(m.group(2))
        times.append(val / 2 if m.group(1) == "<" else val)
    return times


def ping(target: str = "cloudflare", count: int = 5) -> dict:
    host = TARGETS.get(target)
    if host is None:
        raise ValueError(f"Unknown target {target!r}")
    if not shutil.which("ping"):
        return {"target": target, "host": host, "error": "ping command not available"}

    count = max(1, min(count, 20))
    flag = "-n" if platform.system() == "Windows" else "-c"
    try:
        proc = subprocess.run(["ping", flag, str(count), host], capture_output=True,
                              text=True, timeout=count * 3 + 5, errors="replace")
    except subprocess.TimeoutExpired:
        return {"target": target, "host": host, "error": "ping timed out"}

    times = parse_ping_times(proc.stdout)
    if not times:
        lines = (proc.stderr or proc.stdout).strip().splitlines()
        return {"target": target, "host": host, "sent": count, "received": 0, "loss": 100.0,
                "error": lines[-1] if lines else "no replies"}

    jitter = statistics.mean(abs(a - b) for a, b in zip(times, times[1:])) if len(times) > 1 else 0.0
    return {
        "target": target,
        "host": host,
        "sent": count,
        "received": len(times),
        "loss": round(100 * (count - len(times)) / count, 1),
        "min": round(min(times), 1),
        "avg": round(statistics.mean(times), 1),
        "max": round(max(times), 1),
        "jitter": round(jitter, 1),
        "error": None,
    }
