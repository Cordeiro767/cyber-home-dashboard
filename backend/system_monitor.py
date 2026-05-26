"""Local notebook health snapshot for the dashboard."""

from __future__ import annotations

from datetime import timedelta
import time

import psutil


def _bytes_to_gb(value: int) -> float:
    return round(value / (1024**3), 2)


def _format_uptime(seconds: float) -> str:
    delta = timedelta(seconds=int(seconds))
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def _top_processes(limit: int = 5) -> list[dict]:
    processes: list[dict] = []
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
        try:
            info = proc.info
            name = info.get("name") or "unknown"
            if name.lower() in {"system idle process", "idle"}:
                continue
            memory = info.get("memory_info")
            processes.append(
                {
                    "pid": info.get("pid"),
                    "name": name,
                    "cpu_percent": round(float(info.get("cpu_percent") or 0), 1),
                    "memory_mb": round((memory.rss if memory else 0) / (1024**2), 1),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    processes.sort(key=lambda item: (item["cpu_percent"], item["memory_mb"]), reverse=True)
    return processes[:limit]


def _temperatures() -> list[dict]:
    try:
        sensors = psutil.sensors_temperatures(fahrenheit=False)
    except (AttributeError, OSError):
        return []
    temps: list[dict] = []
    for name, entries in sensors.items():
        for entry in entries:
            if entry.current is None:
                continue
            temps.append(
                {
                    "sensor": name,
                    "label": entry.label or name,
                    "current_c": round(float(entry.current), 1),
                }
            )
    return temps[:8]


def get_system_status() -> dict:
    cpu_percent = psutil.cpu_percent(interval=0.15)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time
    temperatures = _temperatures()

    return {
        "cpu_percent": round(cpu_percent, 1),
        "ram": {
            "percent": round(memory.percent, 1),
            "used_gb": _bytes_to_gb(memory.used),
            "total_gb": _bytes_to_gb(memory.total),
        },
        "disk": {
            "percent": round(disk.percent, 1),
            "used_gb": _bytes_to_gb(disk.used),
            "total_gb": _bytes_to_gb(disk.total),
        },
        "uptime": _format_uptime(uptime_seconds),
        "uptime_seconds": int(uptime_seconds),
        "top_processes": _top_processes(),
        "temperatures": temperatures,
        "temperature_available": bool(temperatures),
    }
