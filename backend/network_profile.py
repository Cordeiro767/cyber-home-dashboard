"""Detect and persist local network profiles."""

from __future__ import annotations

import os
import ipaddress
import platform
import sqlite3
import subprocess

from internet_health import get_gateway_ip

IMPORTED_NETWORK_NAME = "Rede antiga/importada"


def _subprocess_flags() -> int:
    if platform.system().lower() == "windows":
        return subprocess.CREATE_NO_WINDOW
    return 0


def detect_ssid() -> str | None:
    if platform.system().lower() != "windows":
        return None
    try:
        result = subprocess.run(
            ["netsh", "wlan", "show", "interfaces"],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=_subprocess_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        clean = line.strip()
        if clean.lower().startswith("ssid") and "bssid" not in clean.lower():
            _, _, value = clean.partition(":")
            return value.strip() or None
    return None


def detect_current_network_info() -> dict:
    subnet = os.getenv("ALLOWED_NETWORK", "192.168.1.0/24")
    gateway = get_gateway_ip()
    try:
        network = ipaddress.ip_network(subnet, strict=False)
        if not gateway or ipaddress.ip_address(gateway) not in network:
            gateway = str(next(network.hosts()))
    except (ValueError, StopIteration):
        gateway = gateway or ""
    ssid = detect_ssid()
    name = ssid or f"Rede {subnet}"
    return {
        "name": name,
        "gateway_ip": gateway or "",
        "subnet": subnet,
        "ssid": ssid or "",
    }


def ensure_imported_network(conn: sqlite3.Connection) -> int:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO networks (name, gateway_ip, subnet, ssid, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(gateway_ip, subnet, ssid) DO UPDATE SET last_seen = excluded.last_seen
        """,
        (IMPORTED_NETWORK_NAME, "", "imported", "", now, now),
    )
    row = conn.execute(
        "SELECT id FROM networks WHERE name = ? AND subnet = ?",
        (IMPORTED_NETWORK_NAME, "imported"),
    ).fetchone()
    return int(row["id"] if hasattr(row, "keys") else row[0])


def ensure_current_network(conn: sqlite3.Connection) -> dict:
    info = detect_current_network_info()
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO networks (name, gateway_ip, subnet, ssid, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(gateway_ip, subnet, ssid) DO UPDATE SET last_seen = excluded.last_seen
        """,
        (
            info["name"],
            info["gateway_ip"],
            info["subnet"],
            info["ssid"],
            now,
            now,
        ),
    )
    row = conn.execute(
        """
        SELECT * FROM networks
        WHERE gateway_ip = ? AND subnet = ? AND ssid = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (info["gateway_ip"], info["subnet"], info["ssid"]),
    ).fetchone()
    return dict(row)


def _now_iso() -> str:
    from database import _now_iso as db_now

    return db_now()
