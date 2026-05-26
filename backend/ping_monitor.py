"""ICMP latency measurement for allowed local hosts only."""

import platform
import re
import subprocess

from scanner import PING_TIMEOUT_MS, _is_allowed, _subprocess_flags


def measure_latency_ms(ip: str) -> float | None:
    """Ping once and return round-trip ms, or None if unreachable."""
    if not _is_allowed(ip):
        return None

    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(PING_TIMEOUT_MS), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=_subprocess_flags(),
        )
        if result.returncode != 0:
            return None
        return _parse_ping_ms(result.stdout)
    except (subprocess.TimeoutExpired, OSError):
        return None


def _parse_ping_ms(output: str) -> float | None:
    patterns = [
        r"(?:tempo|time)[=<]\s*(\d+)\s*ms",
        r"Average\s*=\s*(\d+)\s*ms",
        r"min/avg/max[^=]*=\s*[\d.]+/([\d.]+)/",
        r"round-trip min/avg/max[^=]*=\s*[\d.]+/([\d.]+)/",
    ]
    for pattern in patterns:
        match = re.search(pattern, output, re.IGNORECASE)
        if match:
            try:
                return round(float(match.group(1)), 1)
            except ValueError:
                continue
    if re.search(r"(?:tempo|time)<1\s*ms", output, re.IGNORECASE):
        return 0.5
    return None


def measure_latencies(ips: list[str], max_workers: int = 20) -> dict[str, float | None]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    allowed = [ip for ip in ips if _is_allowed(ip)]
    results: dict[str, float | None] = {ip: None for ip in allowed}
    if not allowed:
        return results

    with ThreadPoolExecutor(max_workers=min(max_workers, len(allowed))) as pool:
        futures = {pool.submit(measure_latency_ms, ip): ip for ip in allowed}
        for future in as_completed(futures):
            ip = futures[future]
            results[ip] = future.result()
    return results
