"""Local network scanner - restricted to configured subnet only."""

import ipaddress
import os
import platform
import re
import shutil
import socket
import subprocess
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

ALLOWED_NETWORK = ipaddress.ip_network(os.getenv("ALLOWED_NETWORK", "192.168.1.0/24"))
USE_NMAP = os.getenv("USE_NMAP", "true").strip().lower() in ("1", "true", "yes", "on")
FALLBACK_SWEEP = os.getenv("FALLBACK_SWEEP", "false").strip().lower() in ("1", "true", "yes", "on")
COMMON_PORTS = [21, 22, 23, 25, 53, 80, 110, 143, 443, 445, 993, 995, 3000, 3389, 5000, 5900, 8000, 8080, 8443, 8888]
PING_TIMEOUT_MS = 500
PORT_TIMEOUT = 0.4
MAX_WORKERS = 40
NMAP_HOST_TIMEOUT = "5s"
NMAP_MAX_RETRIES = "1"


@dataclass
class Device:
    ip: str
    hostname: str
    mac: str | None
    vendor: str | None
    online: bool
    open_ports: list[int]
    latency_ms: float | None = None


def _subprocess_flags() -> int:
    if platform.system().lower() == "windows":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _all_hosts() -> list[str]:
    return [str(ip) for ip in ALLOWED_NETWORK.hosts()]


def _is_allowed(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip) in ALLOWED_NETWORK
    except ValueError:
        return False


def nmap_available() -> bool:
    return shutil.which("nmap") is not None


def _resolve_hostname(ip: str) -> str:
    try:
        name, _, _ = socket.gethostbyaddr(ip)
        return name
    except (socket.herror, socket.gaierror, OSError):
        return "-"


def _normalize_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    mac = mac.strip().upper().replace("-", ":")
    if mac in ("", "-", "UNKNOWN"):
        return None
    return mac


def _lookup_mac_arp(ip: str) -> tuple[str | None, str | None]:
    """Best-effort MAC from local ARP table (no extra packets)."""
    if not _is_allowed(ip):
        return None, None
    system = platform.system().lower()
    try:
        if system == "windows":
            result = subprocess.run(
                ["arp", "-a", ip],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_subprocess_flags(),
            )
        else:
            result = subprocess.run(
                ["arp", "-n", ip],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=_subprocess_flags(),
            )
        if result.returncode != 0:
            return None, None
        match = re.search(
            r"([0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", result.stdout
        )
        if match:
            return _normalize_mac(match.group(0)), None
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None, None


def _arp_table_hosts() -> list[tuple[str, str | None]]:
    """Return hosts already visible in the local ARP table."""
    system = platform.system().lower()
    cmd = ["arp", "-a"] if system == "windows" else ["arp", "-n"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_subprocess_flags(),
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if result.returncode != 0:
        return []

    hosts: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3}).*?(?P<mac>(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2})"
    )
    for line in result.stdout.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        ip = match.group("ip")
        if ip in seen or not _is_allowed(ip):
            continue
        seen.add(ip)
        hosts.append((ip, _normalize_mac(match.group("mac"))))
    return hosts


def _extract_host_addresses(host_el) -> tuple[str | None, str | None, str | None]:
    ip = None
    mac = None
    vendor = None
    for addr in host_el.findall("address"):
        addr_type = addr.get("addrtype")
        if addr_type == "ipv4":
            ip = addr.get("addr")
        elif addr_type == "mac":
            mac = _normalize_mac(addr.get("addr"))
            vendor = addr.get("vendor")
    return ip, mac, vendor


def _ping_host(ip: str) -> bool:
    system = platform.system().lower()
    if system == "windows":
        cmd = ["ping", "-n", "1", "-w", str(PING_TIMEOUT_MS), ip]
    else:
        cmd = ["ping", "-c", "1", "-W", "1", ip]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=3,
            creationflags=_subprocess_flags(),
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _scan_port(ip: str, port: int) -> int | None:
    if not _is_allowed(ip):
        return None
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(PORT_TIMEOUT)
    try:
        if sock.connect_ex((ip, port)) == 0:
            return port
    except OSError:
        pass
    finally:
        sock.close()
    return None


def _scan_ports_fallback(ip: str) -> list[int]:
    open_ports: list[int] = []
    with ThreadPoolExecutor(max_workers=len(COMMON_PORTS)) as pool:
        futures = {pool.submit(_scan_port, ip, p): p for p in COMMON_PORTS}
        for future in as_completed(futures):
            port = future.result()
            if port is not None:
                open_ports.append(port)
    return sorted(open_ports)


def _scan_with_nmap() -> list[Device]:
    cidr = str(ALLOWED_NETWORK)
    ports_str = ",".join(str(p) for p in COMMON_PORTS)

    discovery = subprocess.run(
        [
            "nmap",
            "-sn",
            "-n",
            "--max-retries",
            NMAP_MAX_RETRIES,
            "--host-timeout",
            NMAP_HOST_TIMEOUT,
            "-oX",
            "-",
            cidr,
        ],
        capture_output=True,
        text=True,
        timeout=45,
        creationflags=_subprocess_flags(),
    )
    if discovery.returncode != 0:
        raise RuntimeError(discovery.stderr or "nmap host discovery failed")

    host_info: dict[str, dict] = {}

    root = ET.fromstring(discovery.stdout)
    for host in root.findall(".//host"):
        status = host.find("status")
        if status is None or status.get("state") != "up":
            continue
        ip, mac, vendor = _extract_host_addresses(host)
        if not ip or not _is_allowed(ip):
            continue

        hostname = "-"
        for hostname_el in host.findall("hostnames/hostname"):
            hostname = hostname_el.get("name", hostname)
        if hostname == "-":
            hostname = _resolve_hostname(ip)

        if not mac:
            mac, _ = _lookup_mac_arp(ip)

        host_info[ip] = {
            "hostname": hostname,
            "mac": mac,
            "vendor": vendor or None,
        }

    online_ips = set(host_info.keys())
    ports_by_ip: dict[str, list[int]] = {ip: [] for ip in online_ips}

    if online_ips:
        port_scan = subprocess.run(
            [
                "nmap",
                "-sT",
                "-p",
                ports_str,
                "--open",
                "--max-retries",
                NMAP_MAX_RETRIES,
                "--host-timeout",
                NMAP_HOST_TIMEOUT,
                "-oX",
                "-",
                *sorted(online_ips),
            ],
            capture_output=True,
            text=True,
            timeout=90,
            creationflags=_subprocess_flags(),
        )
        if port_scan.returncode == 0 and port_scan.stdout.strip():
            proot = ET.fromstring(port_scan.stdout)
            for host in proot.findall(".//host"):
                ip, mac, vendor = _extract_host_addresses(host)
                if not ip or ip not in ports_by_ip:
                    continue
                if mac and not host_info[ip].get("mac"):
                    host_info[ip]["mac"] = mac
                if vendor and not host_info[ip].get("vendor"):
                    host_info[ip]["vendor"] = vendor
                for port_el in host.findall(".//port"):
                    if port_el.get("state") == "open":
                        try:
                            ports_by_ip[ip].append(int(port_el.get("portid", 0)))
                        except ValueError:
                            pass

    devices: list[Device] = []
    for ip in sorted(online_ips, key=lambda x: ipaddress.ip_address(x)):
        info = host_info[ip]
        devices.append(
            Device(
                ip=ip,
                hostname=info["hostname"],
                mac=info.get("mac"),
                vendor=info.get("vendor"),
                online=True,
                open_ports=sorted(ports_by_ip.get(ip, [])),
            )
        )
    return devices


def _scan_fallback() -> list[Device]:
    arp_hosts = _arp_table_hosts()
    online_by_ip: dict[str, str | None] = {ip: mac for ip, mac in arp_hosts}

    if FALLBACK_SWEEP:
        hosts = _all_hosts()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_ping_host, ip): ip for ip in hosts}
            for future in as_completed(futures):
                ip = futures[future]
                if future.result():
                    online_by_ip.setdefault(ip, None)

    devices: list[Device] = []
    for ip in sorted(online_by_ip, key=lambda x: ipaddress.ip_address(x)):
        mac = online_by_ip[ip]
        vendor = None
        if not mac:
            mac, vendor = _lookup_mac_arp(ip)
        devices.append(
            Device(
                ip=ip,
                hostname=_resolve_hostname(ip),
                mac=mac,
                vendor=vendor,
                online=True,
                open_ports=_scan_ports_fallback(ip),
            )
        )
    return devices


def run_scan() -> dict:
    """Scan allowed subnet and return discovered hosts."""
    use_nmap = USE_NMAP and nmap_available()
    scanner_name = "nmap" if use_nmap else "fallback"
    try:
        if use_nmap:
            try:
                devices = _scan_with_nmap()
            except Exception:
                devices = _scan_fallback()
                scanner_name = "fallback-after-nmap-error"
        else:
            devices = _scan_fallback()
    except Exception as exc:
        return {
            "network": str(ALLOWED_NETWORK),
            "scanner": scanner_name,
            "error": str(exc),
            "devices": [],
        }

    from ping_monitor import measure_latencies

    latencies = measure_latencies([d.ip for d in devices])
    for device in devices:
        device.latency_ms = latencies.get(device.ip)

    return {
        "network": str(ALLOWED_NETWORK),
        "scanner": scanner_name,
        "devices": [asdict(d) for d in devices],
    }
