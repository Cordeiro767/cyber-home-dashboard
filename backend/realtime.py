"""Build live payloads and push to WebSocket clients."""

from baseline import count_unacknowledged_changes, list_changes
from database import get_counts, get_current_network, get_last_scan, get_network_history, list_devices, list_events
from scanner import ALLOWED_NETWORK
from topology import build_topology
from ws_manager import ws_manager

_scanning = False
_autoscan_enabled = False


def set_scanning(value: bool) -> None:
    global _scanning
    _scanning = value


def set_autoscan_enabled(value: bool) -> None:
    global _autoscan_enabled
    _autoscan_enabled = value


def build_snapshot(terminal_line: str | None = None) -> dict:
    payload = {
        "type": "snapshot",
        "network": str(ALLOWED_NETWORK),
        "current_network": get_current_network(),
        "last_scan": get_last_scan(),
        "scanning": _scanning,
        "counts": get_counts(),
        "devices": list_devices(),
        "events": list_events(limit=50),
        "history": get_network_history(limit=48),
        "topology": build_topology(),
        "autoscan": {"enabled": _autoscan_enabled},
        "changes": list_changes(limit=50),
        "unacknowledged_changes": count_unacknowledged_changes(),
    }
    if terminal_line:
        payload["terminal_line"] = terminal_line
    return payload


def push_update(terminal_line: str | None = None) -> None:
    ws_manager.broadcast_threadsafe(build_snapshot(terminal_line=terminal_line))


def push_terminal(line: str) -> None:
    ws_manager.broadcast_threadsafe({"type": "terminal", "terminal_line": line})
