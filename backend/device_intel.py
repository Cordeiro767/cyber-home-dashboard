"""Device classification and risk scoring (defensive, local only)."""

import json

DEVICE_TYPES = ("router", "laptop", "camera", "phone", "unknown")
TAGS = ("trusted", "iot", "camera", "unknown")
RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")

SENSITIVE_PORTS = {21, 22, 23, 135, 139, 445, 3389, 5900, 873, 4444, 5555}

PORT_SERVICES: dict[int, str] = {
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    110: "POP3",
    143: "IMAP",
    443: "HTTPS",
    445: "SMB",
    993: "IMAPS",
    995: "POP3S",
    3000: "Dev/Web",
    3389: "RDP",
    5000: "UPnP/Dev",
    5900: "VNC",
    8000: "HTTP-Alt",
    8080: "HTTP-Proxy",
    8443: "HTTPS-Alt",
    8888: "HTTP-Alt",
}


def describe_ports(open_ports: list[int]) -> list[dict]:
    return [
        {
            "port": p,
            "service": PORT_SERVICES.get(p, "Desconhecido"),
            "sensitive": p in SENSITIVE_PORTS,
        }
        for p in sorted(open_ports or [])
    ]


def parse_open_ports(value) -> list[int]:
    if value is None:
        return []
    if isinstance(value, list):
        return [int(p) for p in value]
    if isinstance(value, str):
        if not value or value == "[]":
            return []
        try:
            parsed = json.loads(value)
            return [int(p) for p in parsed]
        except (json.JSONDecodeError, TypeError, ValueError):
            return []
    return []


def ports_to_json(ports: list[int] | None) -> str:
    return json.dumps(sorted(ports or []))


def detect_device_type(hostname: str, vendor: str) -> str:
    h = (hostname or "").lower()
    v = (vendor or "").lower()

    router_hints = (
        "router",
        "gateway",
        "vivo",
        "tplink",
        "tp-link",
        "netgear",
        "d-link",
        "openwrt",
        "modem",
    )
    router_vendors = (
        "cisco",
        "tp-link",
        "netgear",
        "d-link",
        "huawei",
        "zte",
        "ubiquiti",
        "mikrotik",
        "asus te",
    )
    if any(x in h for x in router_hints) or any(x in v for x in router_vendors):
        return "router"

    camera_hints = ("cam", "v380", "hikvision", "dvr", "ipcam", "nest-cam", "ring")
    camera_vendors = ("hikvision", "dahua", "v380", "axis", "reolink")
    if any(x in h for x in camera_hints) or any(x in v for x in camera_vendors):
        return "camera"

    phone_hints = ("iphone", "android", "phone", "galaxy", "pixel", "mobile", "redmi")
    if any(x in h for x in phone_hints):
        return "phone"
    if "samsung" in v and "tv" not in h:
        return "phone"
    if "apple" in v and not any(x in h for x in ("mac", "book", "imac")):
        return "phone"

    laptop_hints = ("laptop", "notebook", "desktop", "pc-", "win-", "macbook", "imac")
    laptop_vendors = ("intel", "dell", "lenovo", "hewlett", "hp ", "acer", "msi")
    if any(x in h for x in laptop_hints) or any(x in v for x in laptop_vendors):
        return "laptop"

    return "unknown"


def detect_tag(device_type: str, vendor: str, hostname: str) -> str:
    v = (vendor or "").lower()
    h = (hostname or "").lower()

    if device_type in ("router", "laptop"):
        return "trusted"
    if device_type == "camera":
        return "camera"
    iot_hints = ("esp", "shenzhen", "tuya", "sonoff", "smart", "iot", "hue")
    if device_type == "phone" or any(x in v for x in iot_hints) or any(x in h for x in iot_hints):
        return "iot"
    return "unknown"


def _vendor_missing(vendor: str | None) -> bool:
    return not vendor or vendor.strip() in ("—", "-", "unknown", "Unknown")


def _is_unknown_device(device_type: str, tag: str, vendor: str | None) -> bool:
    return device_type == "unknown" or tag == "unknown" or _vendor_missing(vendor)


def compute_risk(
    status: str,
    device_type: str,
    tag: str,
    vendor: str | None,
    open_ports: list[int],
) -> str:
    ports = open_ports or []
    has_ports = len(ports) > 0
    sensitive = bool(set(ports) & SENSITIVE_PORTS)
    is_new = status == "NEW"
    no_vendor = _vendor_missing(vendor)
    unknown = _is_unknown_device(device_type, tag, vendor)
    known_router_laptop = (
        device_type in ("router", "laptop") and not is_new and not no_vendor
    )

    if unknown and sensitive:
        return "CRITICAL"
    if is_new and has_ports:
        return "HIGH"
    if is_new or no_vendor:
        return "MEDIUM"
    if known_router_laptop:
        return "LOW"
    return "MEDIUM"


def enrich_device(row_dict: dict) -> dict:
    """Add computed risk and display_name to a device dict."""
    ports = parse_open_ports(row_dict.get("open_ports"))
    row_dict["open_ports"] = ports
    row_dict["risk"] = compute_risk(
        row_dict.get("status", "OFFLINE"),
        row_dict.get("device_type", "unknown"),
        row_dict.get("tag", "unknown"),
        row_dict.get("vendor"),
        ports,
    )
    custom = (row_dict.get("custom_name") or "").strip()
    row_dict["display_name"] = custom if custom else row_dict.get("hostname", "—")
    lat = row_dict.get("latency_ms")
    row_dict["latency_ms"] = lat if lat is not None else None
    return row_dict
