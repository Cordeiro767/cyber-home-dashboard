"""Device baseline comparison — local data only, no active probing."""

from device_intel import SENSITIVE_PORTS, parse_open_ports, ports_to_json
from event_logger import log_event

CHANGE_PORT_OPENED = "PORT_OPENED"
CHANGE_PORT_CLOSED = "PORT_CLOSED"
CHANGE_HOSTNAME_CHANGED = "HOSTNAME_CHANGED"
CHANGE_VENDOR_CHANGED = "VENDOR_CHANGED"
CHANGE_MAC_CHANGED = "MAC_CHANGED"
CHANGE_IP_CHANGED = "IP_CHANGED"

BASELINE_CHANGE_TYPES = (
    CHANGE_PORT_OPENED,
    CHANGE_PORT_CLOSED,
    CHANGE_HOSTNAME_CHANGED,
    CHANGE_VENDOR_CHANGED,
    CHANGE_MAC_CHANGED,
    CHANGE_IP_CHANGED,
)

SEVERITY_LOW = "LOW"
SEVERITY_MEDIUM = "MEDIUM"
SEVERITY_HIGH = "HIGH"
SEVERITY_CRITICAL = "CRITICAL"


def init_baseline_tables(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_baselines (
            device_id INTEGER PRIMARY KEY,
            hostname TEXT,
            mac TEXT,
            vendor TEXT,
            ip TEXT NOT NULL,
            open_ports TEXT DEFAULT '[]',
            device_type TEXT,
            tag TEXT,
            risk TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (device_id) REFERENCES devices(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS baseline_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            network_id INTEGER,
            device_id INTEGER NOT NULL,
            change_type TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            severity TEXT NOT NULL,
            created_at TEXT NOT NULL,
            acknowledged INTEGER DEFAULT 0,
            FOREIGN KEY (device_id) REFERENCES devices(id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_baseline_changes_device ON baseline_changes(device_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_baseline_changes_ack ON baseline_changes(acknowledged)"
    )
    existing = {row[1] for row in conn.execute("PRAGMA table_info(baseline_changes)").fetchall()}
    if "network_id" not in existing:
        conn.execute("ALTER TABLE baseline_changes ADD COLUMN network_id INTEGER")


def _now_iso() -> str:
    from database import _now_iso as db_now

    return db_now()


def _norm(value: str | None) -> str:
    if value is None:
        return ""
    v = str(value).strip()
    return "" if v in ("—", "-", "unknown", "Unknown") else v


def _norm_mac(mac: str | None) -> str:
    m = _norm(mac).upper().replace("-", ":")
    return m


def _snapshot_from_row(row) -> dict:
    keys = row.keys() if hasattr(row, "keys") else row
    get = row.__getitem__ if hasattr(row, "__getitem__") else row.get
    ports = parse_open_ports(get("open_ports") if "open_ports" in keys else "[]")
    from device_intel import enrich_device

    device = enrich_device(
        {
            "id": get("id"),
            "ip": get("ip"),
            "hostname": get("hostname") or "—",
            "mac": get("mac"),
            "vendor": get("vendor"),
            "status": get("status"),
            "device_type": get("device_type") if "device_type" in keys else "unknown",
            "tag": get("tag") if "tag" in keys else "unknown",
            "open_ports": ports,
        }
    )
    return {
        "hostname": _norm(device.get("hostname")),
        "mac": _norm_mac(device.get("mac")),
        "vendor": _norm(device.get("vendor")),
        "ip": get("ip"),
        "open_ports": sorted(ports),
        "device_type": device.get("device_type", "unknown"),
        "tag": device.get("tag", "unknown"),
        "risk": device.get("risk", "MEDIUM"),
    }


def _snapshot_from_scan(device: dict) -> dict:
    from device_intel import compute_risk

    ports = sorted(device.get("open_ports") or [])
    dtype = device.get("device_type", "unknown")
    tag = device.get("tag", "unknown")
    vendor = device.get("vendor")
    return {
        "hostname": _norm(device.get("hostname")),
        "mac": _norm_mac(device.get("mac")),
        "vendor": _norm(vendor),
        "ip": device.get("ip"),
        "open_ports": ports,
        "device_type": dtype,
        "tag": tag,
        "risk": compute_risk(
            "ONLINE",
            dtype,
            tag,
            vendor,
            ports,
        ),
    }


def _severity_port_opened(port: int) -> str:
    return SEVERITY_CRITICAL if port in SENSITIVE_PORTS else SEVERITY_MEDIUM


def _record_change(
    conn,
    device_id: int,
    change_type: str,
    old_value: str,
    new_value: str,
    severity: str,
    ip: str,
    hostname: str,
    mac: str | None,
    vendor: str | None,
    network_id: int | None = None,
) -> int:
    created = _now_iso()
    msg = f"{change_type}: {old_value or '—'} → {new_value or '—'}"
    if network_id is None:
        from database import get_current_network_id

        network_id = get_current_network_id(conn)
    conn.execute(
        """
        INSERT INTO baseline_changes
        (network_id, device_id, change_type, old_value, new_value, severity, created_at, acknowledged)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (network_id, device_id, change_type, old_value, new_value, severity, created),
    )
    change_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    from database import _insert_event

    _insert_event(conn, change_type, ip, hostname, mac, vendor, msg, network_id=network_id)
    log_event(change_type, msg, ip=ip, hostname=hostname)
    return change_id


def _save_baseline(conn, device_id: int, snap: dict) -> None:
    conn.execute(
        """
        INSERT INTO device_baselines (
            device_id, hostname, mac, vendor, ip, open_ports,
            device_type, tag, risk, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            hostname = excluded.hostname,
            mac = excluded.mac,
            vendor = excluded.vendor,
            ip = excluded.ip,
            open_ports = excluded.open_ports,
            device_type = excluded.device_type,
            tag = excluded.tag,
            risk = excluded.risk,
            updated_at = excluded.updated_at
        """,
        (
            device_id,
            snap["hostname"],
            snap["mac"],
            snap["vendor"],
            snap["ip"],
            ports_to_json(snap["open_ports"]),
            snap["device_type"],
            snap["tag"],
            snap["risk"],
            _now_iso(),
        ),
    )


def compare_device_baseline(
    conn,
    device_id: int,
    old_row,
    scan_device: dict,
) -> list[dict]:
    """Compare scan data to baseline; establish baseline if missing."""
    current = _snapshot_from_scan(scan_device)
    baseline_row = conn.execute(
        "SELECT * FROM device_baselines WHERE device_id = ?", (device_id,)
    ).fetchone()

    if not baseline_row:
        _save_baseline(conn, device_id, current)
        return []

    baseline = {
        "hostname": _norm(baseline_row["hostname"]),
        "mac": _norm_mac(baseline_row["mac"]),
        "vendor": _norm(baseline_row["vendor"]),
        "ip": baseline_row["ip"],
        "open_ports": parse_open_ports(baseline_row["open_ports"]),
        "device_type": baseline_row["device_type"] or "unknown",
        "tag": baseline_row["tag"] or "unknown",
        "risk": baseline_row["risk"] or "MEDIUM",
    }

    ip = scan_device.get("ip", "")
    hostname = scan_device.get("hostname") or "—"
    mac = scan_device.get("mac")
    vendor = scan_device.get("vendor")
    created: list[dict] = []
    network_id = old_row["network_id"] if "network_id" in old_row.keys() else None

    old_ports = set(baseline["open_ports"])
    new_ports = set(current["open_ports"])
    for port in sorted(new_ports - old_ports):
        cid = _record_change(
            conn,
            device_id,
            CHANGE_PORT_OPENED,
            "",
            str(port),
            _severity_port_opened(port),
            ip,
            hostname,
            mac,
            vendor,
            network_id,
        )
        created.append({"id": cid, "change_type": CHANGE_PORT_OPENED, "device_id": device_id})
    for port in sorted(old_ports - new_ports):
        cid = _record_change(
            conn,
            device_id,
            CHANGE_PORT_CLOSED,
            str(port),
            "",
            SEVERITY_LOW,
            ip,
            hostname,
            mac,
            vendor,
            network_id,
        )
        created.append({"id": cid, "change_type": CHANGE_PORT_CLOSED, "device_id": device_id})

    if baseline["hostname"] and current["hostname"] and baseline["hostname"] != current["hostname"]:
        cid = _record_change(
            conn,
            device_id,
            CHANGE_HOSTNAME_CHANGED,
            baseline["hostname"],
            current["hostname"],
            SEVERITY_LOW,
            ip,
            hostname,
            mac,
            vendor,
            network_id,
        )
        created.append({"id": cid, "change_type": CHANGE_HOSTNAME_CHANGED, "device_id": device_id})

    if baseline["vendor"] and current["vendor"] and baseline["vendor"] != current["vendor"]:
        cid = _record_change(
            conn,
            device_id,
            CHANGE_VENDOR_CHANGED,
            baseline["vendor"],
            current["vendor"],
            SEVERITY_MEDIUM,
            ip,
            hostname,
            mac,
            vendor,
            network_id,
        )
        created.append({"id": cid, "change_type": CHANGE_VENDOR_CHANGED, "device_id": device_id})

    if baseline["mac"] and current["mac"] and baseline["mac"] != current["mac"]:
        cid = _record_change(
            conn,
            device_id,
            CHANGE_MAC_CHANGED,
            baseline["mac"],
            current["mac"],
            SEVERITY_HIGH,
            ip,
            hostname,
            mac,
            vendor,
            network_id,
        )
        created.append({"id": cid, "change_type": CHANGE_MAC_CHANGED, "device_id": device_id})

    return created


def detect_mac_ip_drifts(conn, network_id: int | None = None) -> list[dict]:
    """Detect same MAC on different IPs across inventory."""
    rows = conn.execute(
        """
        SELECT id, ip, mac, hostname, vendor, network_id FROM devices
        WHERE mac IS NOT NULL AND mac != '' AND mac != '—'
          AND (? IS NULL OR network_id = ?)
        """
        ,
        (network_id, network_id),
    ).fetchall()
    by_mac: dict[str, list] = {}
    for row in rows:
        mac = _norm_mac(row["mac"])
        if not mac:
            continue
        by_mac.setdefault(mac, []).append(row)

    created = []
    for mac, devices in by_mac.items():
        if len(devices) < 2:
            continue
        ips = {d["ip"] for d in devices}
        if len(ips) < 2:
            continue
        newest = max(devices, key=lambda d: d["id"])
        for d in devices:
            if d["id"] == newest["id"]:
                continue
            existing = conn.execute(
                """
                SELECT id FROM baseline_changes
                WHERE device_id = ? AND change_type = ? AND acknowledged = 0
                LIMIT 1
                """,
                (d["id"], CHANGE_IP_CHANGED),
            ).fetchone()
            if existing:
                continue
            cid = _record_change(
                conn,
                d["id"],
                CHANGE_IP_CHANGED,
                d["ip"],
                newest["ip"],
                SEVERITY_HIGH,
                d["ip"],
                d["hostname"] or "—",
                mac,
                d["vendor"],
                d["network_id"],
            )
            created.append({"id": cid, "change_type": CHANGE_IP_CHANGED, "device_id": d["id"]})
    return created


def change_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "change_type": row["change_type"],
        "old_value": row["old_value"] or "",
        "new_value": row["new_value"] or "",
        "severity": row["severity"],
        "created_at": row["created_at"],
        "acknowledged": bool(row["acknowledged"]),
    }


def list_changes(acknowledged: bool | None = None, limit: int = 100) -> list[dict]:
    from database import get_connection, get_current_network_id

    query = """
        SELECT c.*, d.ip, d.hostname, d.custom_name, d.mac
        FROM baseline_changes c
        JOIN devices d ON d.id = c.device_id
    """
    params: list = [get_current_network_id()]
    clauses = ["c.network_id = ?"]
    if acknowledged is not None:
        clauses.append("c.acknowledged = ?")
        params.append(1 if acknowledged else 0)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY c.id DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()

    result = []
    for row in rows:
        item = change_to_dict(row)
        item["ip"] = row["ip"]
        item["hostname"] = row["hostname"]
        item["display_name"] = (row["custom_name"] or row["hostname"] or row["ip"] or "—")
        result.append(item)
    return result


def list_device_changes(device_id: int, limit: int = 50) -> list[dict]:
    from database import get_connection

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM baseline_changes
            WHERE device_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (device_id, limit),
        ).fetchall()
    return [change_to_dict(r) for r in rows]


def count_unacknowledged_changes() -> int:
    from database import get_connection, get_current_network_id

    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM baseline_changes WHERE acknowledged = 0 AND network_id = ?",
            (get_current_network_id(),),
        ).fetchone()
    return int(row["n"]) if row else 0


def acknowledge_change(change_id: int) -> dict | None:
    from database import get_connection, get_device_by_id

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM baseline_changes WHERE id = ?", (change_id,)
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE baseline_changes SET acknowledged = 1 WHERE id = ?",
            (change_id,),
        )
        device_id = row["device_id"]
        device = get_device_by_id(device_id)
        if device:
            snap = _snapshot_from_scan(
                {
                    **device,
                    "open_ports": device.get("open_ports", []),
                }
            )
            _save_baseline(conn, device_id, snap)
        conn.commit()

    return change_to_dict(row) | {"acknowledged": True}
