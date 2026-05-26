"""Network topology graph for vis-network (local subnet only)."""

import math
import re

from database import get_connection, list_devices

ROUTER_NODE_ID = "router-central"
GATEWAY_IP_SUFFIX = ".1"


def _now_iso() -> str:
    from database import _now_iso as db_now

    return db_now()


def init_topology_tables(conn) -> None:
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='node_positions'"
    ).fetchone()
    if table_exists:
        existing = {row[1] for row in conn.execute("PRAGMA table_info(node_positions)").fetchall()}
        if "id" not in existing:
            from database import get_current_network_id

            network_id = get_current_network_id(conn)
            conn.execute("ALTER TABLE node_positions RENAME TO node_positions_legacy_network_migration")
            conn.execute(
                """
                CREATE TABLE node_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    network_id INTEGER,
                    node_id TEXT NOT NULL,
                    pos_x REAL NOT NULL,
                    pos_y REAL NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(network_id, node_id)
                )
                """
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO node_positions (network_id, node_id, pos_x, pos_y, updated_at)
                SELECT ?, node_id, pos_x, pos_y, updated_at FROM node_positions_legacy_network_migration
                """,
                (network_id,),
            )
            conn.execute("DROP TABLE node_positions_legacy_network_migration")
            return

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS node_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            network_id INTEGER,
            node_id TEXT NOT NULL,
            pos_x REAL NOT NULL,
            pos_y REAL NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(network_id, node_id)
        )
        """
    )
    existing = {row[1] for row in conn.execute("PRAGMA table_info(node_positions)").fetchall()}
    if "network_id" not in existing:
        from database import get_current_network_id

        conn.execute("ALTER TABLE node_positions ADD COLUMN network_id INTEGER")
        conn.execute(
            "UPDATE node_positions SET network_id = ? WHERE network_id IS NULL",
            (get_current_network_id(conn),),
        )


def get_all_positions() -> dict[str, dict]:
    from database import get_current_network_id

    network_id = get_current_network_id()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT node_id, pos_x, pos_y FROM node_positions WHERE network_id = ?",
            (network_id,),
        ).fetchall()
    return {r["node_id"]: {"x": r["pos_x"], "y": r["pos_y"]} for r in rows}


def save_positions(positions: list[dict]) -> int:
    """Save node positions. node_id must match device-* or router-central."""
    saved = 0
    now = _now_iso()
    with get_connection() as conn:
        from database import get_current_network_id

        network_id = get_current_network_id(conn)
        for item in positions:
            node_id = item.get("node_id", "")
            if not _valid_node_id(node_id):
                continue
            x = float(item.get("x", 0))
            y = float(item.get("y", 0))
            conn.execute(
                """
                INSERT INTO node_positions (network_id, node_id, pos_x, pos_y, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(network_id, node_id) DO UPDATE SET
                    pos_x = excluded.pos_x,
                    pos_y = excluded.pos_y,
                    updated_at = excluded.updated_at
                """,
                (network_id, node_id, x, y, now),
            )
            saved += 1
        conn.commit()
    return saved


def _valid_node_id(node_id: str) -> bool:
    if node_id == ROUTER_NODE_ID:
        return True
    return bool(re.fullmatch(r"device-\d+", node_id))


def device_node_id(device_id: int) -> str:
    return f"device-{device_id}"


def _pick_router(devices: list[dict]) -> dict | None:
    for d in devices:
        if d.get("device_type") == "router":
            return d
    for d in devices:
        if d.get("ip", "").endswith(GATEWAY_IP_SUFFIX):
            return d
    online = [d for d in devices if d.get("status") in ("ONLINE", "NEW")]
    if online:
        return min(online, key=lambda x: x.get("ip", ""))
    return None


def _default_peripheral_position(index: int, total: int, radius: float = 220) -> dict:
    angle = (2 * math.pi * index) / max(total, 1)
    return {"x": radius * math.cos(angle), "y": radius * math.sin(angle)}


def _node_payload(
    node_id: str,
    device: dict | None,
    *,
    is_router: bool = False,
    x: float = 0,
    y: float = 0,
) -> dict:
    if device:
        return {
            "id": node_id,
            "device_id": device.get("id"),
            "label": device.get("display_name") or device.get("hostname") or device.get("ip"),
            "ip": device.get("ip"),
            "hostname": device.get("hostname"),
            "vendor": device.get("vendor"),
            "latency_ms": device.get("latency_ms"),
            "status": device.get("status"),
            "risk": device.get("risk"),
            "device_type": device.get("device_type", "unknown"),
            "tag": device.get("tag", "unknown"),
            "is_router": is_router,
            "x": x,
            "y": y,
        }
    return {
        "id": node_id,
        "device_id": None,
        "label": "Gateway",
        "ip": "192.168.1.1",
        "hostname": "router",
        "vendor": "—",
        "latency_ms": None,
        "status": "ONLINE",
        "risk": "LOW",
        "device_type": "router",
        "tag": "trusted",
        "is_router": True,
        "x": x,
        "y": y,
    }


def build_topology(devices: list[dict] | None = None) -> dict:
    devices = devices if devices is not None else list_devices()
    positions = get_all_positions()
    router_device = _pick_router(devices)

    if router_device:
        center_id = device_node_id(router_device["id"])
        center_is_synthetic = False
    else:
        center_id = ROUTER_NODE_ID
        center_is_synthetic = True

    center_pos = positions.get(center_id, {"x": 0, "y": 0})
    nodes: list[dict] = []

    if center_is_synthetic:
        nodes.append(
            _node_payload(
                ROUTER_NODE_ID,
                None,
                is_router=True,
                x=center_pos["x"],
                y=center_pos["y"],
            )
        )
    else:
        nodes.append(
            _node_payload(
                center_id,
                router_device,
                is_router=True,
                x=center_pos["x"],
                y=center_pos["y"],
            )
        )

    peripheral = [
        d
        for d in devices
        if not (
            router_device
            and d.get("id") == router_device.get("id")
        )
    ]

    for i, device in enumerate(peripheral):
        nid = device_node_id(device["id"])
        pos = positions.get(nid)
        if not pos:
            pos = _default_peripheral_position(i, len(peripheral))
        nodes.append(
            _node_payload(
                nid,
                device,
                is_router=False,
                x=pos["x"],
                y=pos["y"],
            )
        )

    actual_center = ROUTER_NODE_ID if center_is_synthetic else center_id
    edges = [{"from": actual_center, "to": n["id"]} for n in nodes if n["id"] != actual_center]

    return {
        "center_id": actual_center,
        "nodes": nodes,
        "edges": edges,
    }
