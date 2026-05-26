"""Append-only event log file."""

from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "events.log"


def _ensure_log_dir() -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_event(
    event_type: str,
    message: str,
    ip: str | None = None,
    hostname: str | None = None,
) -> None:
    _ensure_log_dir()
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    ip_part = ip or "—"
    host_part = hostname or "—"
    line = f"[{ts}] {event_type} | {ip_part} | {host_part} | {message}\n"
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line)
