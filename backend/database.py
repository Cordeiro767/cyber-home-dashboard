"""SQLite persistence for devices and events."""

import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from device_intel import (
    DEVICE_TYPES,
    TAGS,
    detect_device_type,
    detect_tag,
    enrich_device,
    ports_to_json,
)
from event_logger import log_event
from network_profile import ensure_current_network, ensure_imported_network

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "network.db"

STATUS_NEW = "NEW"
STATUS_ONLINE = "ONLINE"
STATUS_OFFLINE = "OFFLINE"

EVENT_DEVICE_NEW = "DEVICE_NEW"
EVENT_DEVICE_OFFLINE = "DEVICE_OFFLINE"
EVENT_DEVICE_BACK_ONLINE = "DEVICE_BACK_ONLINE"

META_LAST_SCAN = "last_scan_at"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _migrate_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(devices)").fetchall()}
    migrations = {
        "custom_name": "TEXT",
        "device_type": "TEXT DEFAULT 'unknown'",
        "tag": "TEXT DEFAULT 'unknown'",
        "open_ports": "TEXT DEFAULT '[]'",
        "latency_ms": "REAL",
        "notes": "TEXT",
    }
    for col, col_type in migrations.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE devices ADD COLUMN {col} {col_type}")


def _init_network_tables(conn: sqlite3.Connection) -> int:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS networks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            gateway_ip TEXT NOT NULL DEFAULT '',
            subnet TEXT NOT NULL,
            ssid TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            UNIQUE(gateway_ip, subnet, ssid)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_networks_last_seen ON networks(last_seen DESC)")
    return ensure_imported_network(conn)


def _devices_has_global_ip_unique(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA index_list(devices)").fetchall()
    for row in rows:
        if not row[2]:
            continue
        index_name = row[1]
        cols = [info[2] for info in conn.execute(f"PRAGMA index_info({index_name})").fetchall()]
        if cols == ["ip"]:
            return True
    return False


def _migrate_devices_for_networks(conn: sqlite3.Connection, imported_network_id: int) -> None:
    if not conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='devices'").fetchone():
        return
    cols = _table_columns(conn, "devices")
    if "network_id" in cols and not _devices_has_global_ip_unique(conn):
        return

    conn.execute("ALTER TABLE devices RENAME TO devices_legacy_network_migration")
    conn.execute(
        """
        CREATE TABLE devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            network_id INTEGER NOT NULL,
            ip TEXT NOT NULL,
            hostname TEXT,
            mac TEXT,
            vendor TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            status TEXT NOT NULL,
            custom_name TEXT,
            device_type TEXT DEFAULT 'unknown',
            tag TEXT DEFAULT 'unknown',
            open_ports TEXT DEFAULT '[]',
            latency_ms REAL,
            notes TEXT,
            UNIQUE(network_id, ip),
            FOREIGN KEY (network_id) REFERENCES networks(id)
        )
        """
    )
    old_cols = _table_columns(conn, "devices_legacy_network_migration")
    select_cols = [
        "id",
        f"{imported_network_id} AS network_id" if "network_id" not in old_cols else "network_id",
        "ip",
        "hostname",
        "mac",
        "vendor",
        "first_seen",
        "last_seen",
        "status",
        "custom_name" if "custom_name" in old_cols else "NULL AS custom_name",
        "device_type" if "device_type" in old_cols else "'unknown' AS device_type",
        "tag" if "tag" in old_cols else "'unknown' AS tag",
        "open_ports" if "open_ports" in old_cols else "'[]' AS open_ports",
        "latency_ms" if "latency_ms" in old_cols else "NULL AS latency_ms",
        "notes" if "notes" in old_cols else "NULL AS notes",
    ]
    conn.execute(
        f"""
        INSERT OR IGNORE INTO devices (
            id, network_id, ip, hostname, mac, vendor, first_seen, last_seen, status,
            custom_name, device_type, tag, open_ports, latency_ms, notes
        )
        SELECT {", ".join(select_cols)} FROM devices_legacy_network_migration
        """
    )
    conn.execute("DROP TABLE devices_legacy_network_migration")


def _migrate_network_columns(conn: sqlite3.Connection, imported_network_id: int) -> None:
    for table in ("events", "baseline_changes", "network_stats"):
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
            _ensure_column(conn, table, "network_id", "INTEGER")
            conn.execute(
                f"UPDATE {table} SET network_id = ? WHERE network_id IS NULL",
                (imported_network_id,),
            )


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        imported_network_id = _init_network_tables(conn)
        _migrate_devices_for_networks(conn, imported_network_id)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                network_id INTEGER NOT NULL,
                ip TEXT NOT NULL,
                hostname TEXT,
                mac TEXT,
                vendor TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                status TEXT NOT NULL,
                custom_name TEXT,
                device_type TEXT DEFAULT 'unknown',
                tag TEXT DEFAULT 'unknown',
                open_ports TEXT DEFAULT '[]',
                UNIQUE(network_id, ip),
                FOREIGN KEY (network_id) REFERENCES networks(id)
            )
            """
        )
        _migrate_columns(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                network_id INTEGER,
                event_type TEXT NOT NULL,
                ip TEXT,
                hostname TEXT,
                mac TEXT,
                vendor TEXT,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(device_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at DESC)"
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS network_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                online_count INTEGER NOT NULL,
                offline_count INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_network_stats_at ON network_stats(recorded_at)"
        )
        from baseline import init_baseline_tables
        from topology import init_topology_tables

        init_topology_tables(conn)
        init_baseline_tables(conn)
        _migrate_network_columns(conn, imported_network_id)
        conn.commit()


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _row_base(row: sqlite3.Row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "network_id": row["network_id"] if "network_id" in keys else None,
        "ip": row["ip"],
        "hostname": row["hostname"] or "—",
        "mac": row["mac"] or "—",
        "vendor": row["vendor"] or "—",
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
        "status": row["status"],
        "custom_name": row["custom_name"] if "custom_name" in keys else None,
        "device_type": row["device_type"] if "device_type" in keys else "unknown",
        "tag": row["tag"] if "tag" in keys else "unknown",
        "open_ports": row["open_ports"] if "open_ports" in keys else "[]",
        "latency_ms": row["latency_ms"] if "latency_ms" in keys else None,
        "notes": row["notes"] if "notes" in keys else "",
    }


def device_to_dict(row: sqlite3.Row) -> dict:
    return enrich_device(_row_base(row))


def event_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "network_id": row["network_id"] if "network_id" in row.keys() else None,
        "event_type": row["event_type"],
        "ip": row["ip"] or "—",
        "hostname": row["hostname"] or "—",
        "mac": row["mac"] or "—",
        "vendor": row["vendor"] or "—",
        "message": row["message"],
        "created_at": row["created_at"],
    }


def _insert_event(
    conn: sqlite3.Connection,
    event_type: str,
    ip: str,
    hostname: str,
    mac: str | None,
    vendor: str | None,
    message: str,
    network_id: int | None = None,
) -> None:
    created = _now_iso()
    conn.execute(
        """
        INSERT INTO events (network_id, event_type, ip, hostname, mac, vendor, message, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (network_id or get_current_network_id(conn), event_type, ip, hostname, mac, vendor, message, created),
    )
    log_event(event_type, message, ip=ip, hostname=hostname)


def record_network_stats(network_id: int | None = None) -> dict:
    network_id = network_id or get_current_network_id()
    counts = get_counts(network_id=network_id)
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO network_stats (network_id, recorded_at, online_count, offline_count)
            VALUES (?, ?, ?, ?)
            """,
            (network_id, now, counts["online"], counts["offline"]),
        )
        conn.execute(
            """
            DELETE FROM network_stats WHERE id NOT IN (
                SELECT id FROM network_stats ORDER BY id DESC LIMIT 500
            )
            """
        )
        conn.commit()
    return {"recorded_at": now, "online": counts["online"], "offline": counts["offline"]}


def get_network_history(limit: int = 48, network_id: str | int | None = "current") -> list[dict]:
    resolved_network_id = resolve_network_id(network_id)
    with get_connection() as conn:
        if resolved_network_id is None:
            rows = conn.execute(
                """
                SELECT recorded_at, online_count, offline_count
                FROM network_stats
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT recorded_at, online_count, offline_count
                FROM network_stats
                WHERE network_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (resolved_network_id, limit),
            ).fetchall()
    rows = list(reversed(rows))
    return [
        {
            "recorded_at": r["recorded_at"],
            "online": r["online_count"],
            "offline": r["offline_count"],
        }
        for r in rows
    ]


def _auto_classify(hostname: str, vendor: str | None) -> tuple[str, str]:
    dtype = detect_device_type(hostname, vendor or "")
    tag = detect_tag(dtype, vendor or "", hostname)
    return dtype, tag


def set_last_scan() -> str:
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (META_LAST_SCAN, now),
        )
        conn.commit()
    return now


def get_last_scan() -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = ?", (META_LAST_SCAN,)
        ).fetchone()
    return row["value"] if row else None


def get_current_network_id(conn: sqlite3.Connection | None = None) -> int:
    if conn is not None:
        return int(ensure_current_network(conn)["id"])
    with get_connection() as inner:
        network = ensure_current_network(inner)
        inner.commit()
        return int(network["id"])


def get_current_network() -> dict:
    with get_connection() as conn:
        network = ensure_current_network(conn)
        conn.commit()
        return network


def list_networks() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT n.*,
                   COUNT(d.id) AS device_count,
                   SUM(CASE WHEN d.status IN ('ONLINE', 'NEW') THEN 1 ELSE 0 END) AS online_count
            FROM networks n
            LEFT JOIN devices d ON d.network_id = n.id
            GROUP BY n.id
            ORDER BY n.last_seen DESC, n.id DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def update_network(network_id: int, name: str) -> dict | None:
    clean = name.strip()
    if not clean:
        raise ValueError("Nome da rede nao pode ficar vazio")
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM networks WHERE id = ?", (network_id,)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE networks SET name = ?, last_seen = ? WHERE id = ?",
            (clean, _now_iso(), network_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM networks WHERE id = ?", (network_id,)).fetchone()
        return dict(updated)


def resolve_network_id(network_id: str | int | None = "current") -> int | None:
    if network_id in (None, "", "current"):
        return get_current_network_id()
    if network_id == "all":
        return None
    return int(network_id)


def get_device_by_id(device_id: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
    return device_to_dict(row) if row else None


def list_devices(
    status: str | None = None,
    device_type: str | None = None,
    risk: str | None = None,
    network_id: int | str | None = "current",
) -> list[dict]:
    resolved_network_id = resolve_network_id(network_id)
    with get_connection() as conn:
        if resolved_network_id is None:
            rows = conn.execute("SELECT * FROM devices ORDER BY network_id, ip").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM devices WHERE network_id = ? ORDER BY ip",
                (resolved_network_id,),
            ).fetchall()

    devices = [device_to_dict(r) for r in rows]

    if status:
        devices = [d for d in devices if d["status"].upper() == status.upper()]
    if device_type:
        devices = [d for d in devices if d["device_type"].lower() == device_type.lower()]
    if risk:
        devices = [d for d in devices if d["risk"].upper() == risk.upper()]

    return devices


def list_events(limit: int = 100, network_id: int | str | None = "current") -> list[dict]:
    resolved_network_id = resolve_network_id(network_id)
    with get_connection() as conn:
        if resolved_network_id is None:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events WHERE network_id = ? ORDER BY id DESC LIMIT ?",
                (resolved_network_id, limit),
            ).fetchall()
    return [event_to_dict(r) for r in rows]


def get_counts(network_id: int | str | None = "current") -> dict:
    devices = list_devices(network_id=network_id)
    online = sum(1 for d in devices if d["status"] in (STATUS_ONLINE, STATUS_NEW))
    offline = sum(1 for d in devices if d["status"] == STATUS_OFFLINE)
    new = sum(1 for d in devices if d["status"] == STATUS_NEW)
    return {
        "total": len(devices),
        "online": online,
        "offline": offline,
        "new": new,
    }


def mark_devices_seen() -> int:
    network_id = get_current_network_id()
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE devices SET status = ? WHERE status = ? AND network_id = ?",
            (STATUS_ONLINE, STATUS_NEW, network_id),
        )
        conn.commit()
        return cur.rowcount


def get_device_events(device_id: int, limit: int = 20) -> list[dict]:
    device = get_device_by_id(device_id)
    if not device:
        return []
    ip = device["ip"]
    mac = device.get("mac")
    network_id = device.get("network_id")
    with get_connection() as conn:
        if mac and mac not in ("—", ""):
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE network_id = ? AND (ip = ? OR mac = ?)
                ORDER BY id DESC
                LIMIT ?
                """,
                (network_id, ip, mac, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM events
                WHERE network_id = ? AND ip = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (network_id, ip, limit),
            ).fetchall()
    return [event_to_dict(r) for r in rows]


def update_device_notes(device_id: int, notes: str) -> dict | None:
    if not get_device_by_id(device_id):
        return None
    with get_connection() as conn:
        conn.execute(
            "UPDATE devices SET notes = ? WHERE id = ?",
            (notes.strip(), device_id),
        )
        conn.commit()
    return get_device_by_id(device_id)


def mark_device_trusted(device_id: int) -> dict | None:
    return update_device(device_id, tag="trusted")


def device_export_payload(device_id: int) -> dict | None:
    from device_intel import describe_ports

    device = get_device_by_id(device_id)
    if not device:
        return None
    events = get_device_events(device_id, limit=50)
    return {
        "exported_at": _now_iso(),
        "device": device,
        "ports": describe_ports(device.get("open_ports", [])),
        "events": events,
    }


def update_device(
    device_id: int,
    custom_name: str | None = None,
    device_type: str | None = None,
    tag: str | None = None,
) -> dict | None:
    device = get_device_by_id(device_id)
    if not device:
        return None

    updates: list[str] = []
    params: list = []

    if custom_name is not None:
        updates.append("custom_name = ?")
        params.append(custom_name.strip() or None)
    if device_type is not None:
        if device_type not in DEVICE_TYPES:
            raise ValueError(f"device_type inválido: {device_type}")
        updates.append("device_type = ?")
        params.append(device_type)
    if tag is not None:
        if tag not in TAGS:
            raise ValueError(f"tag inválida: {tag}")
        updates.append("tag = ?")
        params.append(tag)

    if not updates:
        return device

    params.append(device_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE devices SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()

    return get_device_by_id(device_id)


def devices_to_csv() -> str:
    output = io.StringIO()
    devices = list_devices(network_id="current")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "id",
            "network_id",
            "ip",
            "display_name",
            "custom_name",
            "hostname",
            "mac",
            "vendor",
            "device_type",
            "tag",
            "risk",
            "latency_ms",
            "open_ports",
            "first_seen",
            "last_seen",
            "status",
        ],
    )
    writer.writeheader()
    for d in devices:
        row = {**d}
        row["open_ports"] = ",".join(str(p) for p in d.get("open_ports", []))
        writer.writerow(row)
    return output.getvalue()


def sync_scan_results(scanned: list[dict]) -> dict:
    now = _now_iso()
    seen_ips = {d["ip"] for d in scanned}
    new_count = 0
    events_created: list[dict] = []
    baseline_changes_created: list[dict] = []

    with get_connection() as conn:
        network_id = get_current_network_id(conn)
        existing_rows = conn.execute(
            "SELECT * FROM devices WHERE network_id = ?",
            (network_id,),
        ).fetchall()
        existing = {row["ip"]: row for row in existing_rows}

        for device in scanned:
            ip = device["ip"]
            hostname = device.get("hostname") or "—"
            mac = device.get("mac")
            vendor = device.get("vendor")
            ports_json = ports_to_json(device.get("open_ports"))
            latency = device.get("latency_ms")

            if ip not in existing:
                dtype, tag = _auto_classify(hostname, vendor)
                conn.execute(
                    """
                    INSERT INTO devices (
                        network_id, ip, hostname, mac, vendor, first_seen, last_seen, status,
                        device_type, tag, open_ports, latency_ms
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        network_id,
                        ip,
                        hostname,
                        mac,
                        vendor,
                        now,
                        now,
                        STATUS_NEW,
                        dtype,
                        tag,
                        ports_json,
                        latency,
                    ),
                )
                new_count += 1
                msg = f"Novo dispositivo detectado: {ip} ({hostname})"
                _insert_event(
                    conn, EVENT_DEVICE_NEW, ip, hostname, mac, vendor, msg, network_id=network_id
                )
                events_created.append({"event_type": EVENT_DEVICE_NEW, "ip": ip})
            else:
                from baseline import compare_device_baseline

                row = existing[ip]
                device_id = row["id"]
                baseline_changes_created.extend(
                    compare_device_baseline(conn, device_id, row, device)
                )
                old_status = row["status"]
                keys = row.keys()
                current_type = row["device_type"] if "device_type" in keys else "unknown"
                current_tag = row["tag"] if "tag" in keys else "unknown"

                dtype, auto_tag = _auto_classify(hostname, vendor)
                if current_type != "unknown":
                    dtype = current_type
                if current_tag != "unknown":
                    tag = current_tag
                else:
                    tag = auto_tag

                if old_status == STATUS_OFFLINE:
                    msg = f"Dispositivo voltou online: {ip} ({hostname})"
                    _insert_event(
                        conn,
                        EVENT_DEVICE_BACK_ONLINE,
                        ip,
                        hostname,
                        mac or row["mac"],
                        vendor or row["vendor"],
                        msg,
                        network_id=network_id,
                    )
                    events_created.append(
                        {"event_type": EVENT_DEVICE_BACK_ONLINE, "ip": ip}
                    )
                    new_status = STATUS_ONLINE
                elif old_status == STATUS_NEW:
                    new_status = STATUS_NEW
                else:
                    new_status = STATUS_ONLINE

                conn.execute(
                    """
                    UPDATE devices
                    SET hostname = ?, mac = COALESCE(?, mac), vendor = COALESCE(?, vendor),
                        last_seen = ?, status = ?, device_type = ?, tag = ?,
                        open_ports = ?, latency_ms = ?
                    WHERE network_id = ? AND ip = ?
                    """,
                    (
                        hostname,
                        mac,
                        vendor,
                        now,
                        new_status,
                        dtype,
                        tag,
                        ports_json,
                        latency,
                        network_id,
                        ip,
                    ),
                )

        for ip, row in existing.items():
            if ip not in seen_ips and row["status"] != STATUS_OFFLINE:
                conn.execute(
                    "UPDATE devices SET status = ? WHERE network_id = ? AND ip = ?",
                    (STATUS_OFFLINE, network_id, ip),
                )
                hostname = row["hostname"] or "—"
                msg = f"Dispositivo offline: {ip} ({hostname})"
                _insert_event(
                    conn,
                    EVENT_DEVICE_OFFLINE,
                    ip,
                    hostname,
                    row["mac"],
                    row["vendor"],
                    msg,
                    network_id=network_id,
                )
                events_created.append({"event_type": EVENT_DEVICE_OFFLINE, "ip": ip})

        from baseline import detect_mac_ip_drifts

        baseline_changes_created.extend(detect_mac_ip_drifts(conn, network_id=network_id))

        conn.commit()

    devices = list_devices(network_id=network_id)
    return {
        "devices": devices,
        "new_count": new_count,
        "new_devices": [d for d in devices if d["status"] == STATUS_NEW],
        "events_created": events_created,
        "baseline_changes": baseline_changes_created,
    }
