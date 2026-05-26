"""Small, controlled internet health checks."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import os
import platform
import re
import subprocess


PING_HISTORY: deque[dict] = deque(maxlen=60)


def _subprocess_flags() -> int:
    if platform.system().lower() == "windows":
        return subprocess.CREATE_NO_WINDOW
    return 0


def get_gateway_ip() -> str | None:
    env_gateway = os.getenv("GATEWAY_IP")
    if env_gateway:
        return env_gateway.strip()
    configured_subnet = os.getenv("ALLOWED_NETWORK")
    allowed_network = None
    if configured_subnet:
        try:
            allowed_network = ipaddress.ip_network(configured_subnet, strict=False)
        except ValueError:
            allowed_network = None

    try:
        result = subprocess.run(
            ["route", "print", "-4", "0.0.0.0"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=_subprocess_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    gateways = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
            gateways.append(parts[2])
    if allowed_network:
        for gateway in gateways:
            try:
                if ipaddress.ip_address(gateway) in allowed_network:
                    return gateway
            except ValueError:
                continue
        try:
            return str(next(allowed_network.hosts()))
        except StopIteration:
            return None
    if gateways:
        return gateways[0]
    return None


def ping_host(host: str, timeout_ms: int = 1000) -> dict:
    if platform.system().lower() == "windows":
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        cmd = ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), host]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_subprocess_flags(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"host": host, "ok": False, "latency_ms": None, "error": str(exc)}

    output = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"(?:time|tempo)[=<]\s*(\d+)\s*ms", output, re.IGNORECASE)
    latency = int(match.group(1)) if match else None
    return {
        "host": host,
        "ok": result.returncode == 0,
        "latency_ms": latency,
        "error": None if result.returncode == 0 else "ping failed",
    }


def get_network_health() -> dict:
    gateway = get_gateway_ip()
    with ThreadPoolExecutor(max_workers=2) as pool:
        gateway_future = pool.submit(ping_host, gateway) if gateway else None
        internet_future = pool.submit(ping_host, "8.8.8.8")
        gateway_ping = (
            gateway_future.result()
            if gateway_future
            else {"host": None, "ok": False, "latency_ms": None, "error": "gateway not found"}
        )
        internet_ping = internet_future.result()

    latencies = [
        item["latency_ms"]
        for item in (gateway_ping, internet_ping)
        if item.get("ok") and item.get("latency_ms") is not None
    ]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else None

    if internet_ping["ok"] and gateway_ping["ok"] and (avg_latency is None or avg_latency < 150):
        status = "OK"
    elif internet_ping["ok"] or gateway_ping["ok"]:
        status = "INSTAVEL"
    else:
        status = "OFFLINE"

    point = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "gateway_ms": gateway_ping.get("latency_ms"),
        "internet_ms": internet_ping.get("latency_ms"),
        "status": status,
    }
    PING_HISTORY.append(point)

    return {
        "status": status,
        "gateway": gateway,
        "gateway_ping": gateway_ping,
        "internet_ping": internet_ping,
        "average_latency_ms": avg_latency,
        "history": list(PING_HISTORY),
    }
