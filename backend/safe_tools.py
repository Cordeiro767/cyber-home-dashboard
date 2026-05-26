"""Allowlisted command runner for local diagnostics."""

from __future__ import annotations

import platform
import subprocess

from internet_health import get_gateway_ip, ping_host
from system_monitor import get_system_status


SAFE_ACTIONS = {
    "ping_gateway": "Ping gateway local",
    "ping_google": "Ping 8.8.8.8",
    "ipconfig": "Mostrar configuracao IP",
    "routes": "Mostrar rotas IPv4",
    "system_status": "Status do sistema",
}


def _subprocess_flags() -> int:
    if platform.system().lower() == "windows":
        return subprocess.CREATE_NO_WINDOW
    return 0


def _run_command(args: list[str]) -> dict:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=_subprocess_flags(),
        )
        output = result.stdout.strip() or result.stderr.strip()
        return {"ok": result.returncode == 0, "exit_code": result.returncode, "output": output}
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": None, "output": "Comando interrompido por timeout de 5s."}
    except OSError as exc:
        return {"ok": False, "exit_code": None, "output": str(exc)}


def run_safe_action(action: str) -> dict:
    if action not in SAFE_ACTIONS:
        raise ValueError("acao nao permitida")

    if action == "ping_gateway":
        gateway = get_gateway_ip()
        if not gateway:
            return {"action": action, "label": SAFE_ACTIONS[action], "ok": False, "output": "Gateway local nao encontrado."}
        result = ping_host(gateway)
        return {
            "action": action,
            "label": SAFE_ACTIONS[action],
            "ok": result["ok"],
            "output": f"gateway={gateway} ok={result['ok']} latency_ms={result['latency_ms']}",
        }

    if action == "ping_google":
        result = ping_host("8.8.8.8")
        return {
            "action": action,
            "label": SAFE_ACTIONS[action],
            "ok": result["ok"],
            "output": f"host=8.8.8.8 ok={result['ok']} latency_ms={result['latency_ms']}",
        }

    if action == "ipconfig":
        return {"action": action, "label": SAFE_ACTIONS[action], **_run_command(["ipconfig"])}

    if action == "routes":
        return {"action": action, "label": SAFE_ACTIONS[action], **_run_command(["route", "print", "-4"])}

    status = get_system_status()
    lines = [
        f"CPU: {status['cpu_percent']}%",
        f"RAM: {status['ram']['percent']}% ({status['ram']['used_gb']}/{status['ram']['total_gb']} GB)",
        f"Disco: {status['disk']['percent']}% ({status['disk']['used_gb']}/{status['disk']['total_gb']} GB)",
        f"Uptime: {status['uptime']}",
    ]
    return {"action": action, "label": SAFE_ACTIONS[action], "ok": True, "output": "\n".join(lines)}
