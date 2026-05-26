"""Cyber Home Dashboard - FastAPI backend v1.0."""

import threading
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from autoscan import AutoScanManager
from baseline import (
    BASELINE_CHANGE_TYPES,
    acknowledge_change,
    count_unacknowledged_changes,
    list_changes,
    list_device_changes,
)
from config import SCAN_INTERVAL_SECONDS
from database import (
    device_export_payload,
    devices_to_csv,
    get_counts,
    get_device_by_id,
    get_device_events,
    get_current_network,
    get_last_scan,
    get_network_history,
    init_db,
    list_devices,
    list_events,
    list_networks,
    mark_device_trusted,
    mark_devices_seen,
    record_network_stats,
    set_last_scan,
    sync_scan_results,
    update_device,
    update_device_notes,
    update_network,
)
from device_intel import DEVICE_TYPES, RISK_LEVELS, TAGS, describe_ports
from internet_health import get_network_health
from realtime import (
    build_snapshot,
    push_terminal,
    push_update,
    set_autoscan_enabled,
    set_scanning,
)
from scanner import ALLOWED_NETWORK, run_scan
from safe_tools import SAFE_ACTIONS, run_safe_action
from system_monitor import get_system_status
from topology import build_topology, save_positions
from ws_manager import ws_manager

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

_scan_lock = threading.Lock()
_scanning = False
_autoscan: AutoScanManager | None = None


class DevicePatch(BaseModel):
    custom_name: str | None = Field(None, max_length=120)
    device_type: Literal["router", "laptop", "camera", "phone", "unknown"] | None = None
    tag: Literal["trusted", "iot", "camera", "unknown"] | None = None


class NodePosition(BaseModel):
    node_id: str = Field(..., max_length=64)
    x: float
    y: float


class TopologyPositionsPatch(BaseModel):
    positions: list[NodePosition]


class DeviceNotesPatch(BaseModel):
    notes: str = Field("", max_length=4000)


class SafeToolRequest(BaseModel):
    action: str = Field(..., max_length=40)


class NetworkPatch(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


def _notify_scan_complete(scan_result: dict, sync: dict) -> None:
    for ev in sync.get("events_created", []):
        push_terminal(f"▸ {ev['event_type']} → {ev.get('ip', '?')}")
    for ch in sync.get("baseline_changes", []):
        push_terminal(f"▸ BASELINE {ch.get('change_type')} · device #{ch.get('device_id')}")
    scanner = scan_result.get("scanner", "?")
    n = len(sync.get("devices", []))
    online = get_counts().get("online", 0)
    push_terminal(f"▸ SCAN OK [{scanner}] · {online} online / {n} total")
    push_update()


def _perform_scan() -> dict:
    global _scanning

    if not _scan_lock.acquire(blocking=False):
        push_terminal("▸ Scan ignorado — já em andamento")
        return {
            "network": str(ALLOWED_NETWORK),
            "scanner": None,
            "error": "Scan já em andamento",
            "devices": list_devices(),
            "new_count": 0,
            "new_devices": [],
            "events_created": [],
            "last_scan": get_last_scan(),
        }

    try:
        _scanning = True
        set_scanning(True)
        push_terminal("▸ Iniciando scan da rede local…")
        push_update()

        scan_result = run_scan()

        if scan_result.get("error"):
            push_terminal(f"▸ ERRO scan: {scan_result['error']}")
            push_update()
            return {
                **scan_result,
                "devices": list_devices(),
                "new_count": 0,
                "new_devices": [],
                "events_created": [],
                "last_scan": get_last_scan(),
            }

        sync = sync_scan_results(scan_result["devices"])
        last_scan = set_last_scan()
        record_network_stats()

        result = {
            "network": scan_result["network"],
            "scanner": scan_result["scanner"],
            "error": None,
            "devices": sync["devices"],
            "new_count": sync["new_count"],
            "new_devices": sync["new_devices"],
            "events_created": sync["events_created"],
            "last_scan": last_scan,
            "history": get_network_history(),
            "topology": build_topology(sync["devices"]),
        }
        _notify_scan_complete(scan_result, sync)
        return result
    finally:
        _scanning = False
        set_scanning(False)
        _scan_lock.release()


def _build_status() -> dict:
    counts = get_counts()
    return {
        "network": str(ALLOWED_NETWORK),
        "current_network": get_current_network(),
        "last_scan": get_last_scan(),
        "scanning": _scanning,
        "counts": counts,
        "unacknowledged_changes": count_unacknowledged_changes(),
        "autoscan": {
            "enabled": _autoscan.enabled if _autoscan else False,
            "interval_seconds": _autoscan.interval_seconds
            if _autoscan
            else SCAN_INTERVAL_SECONDS,
        },
    }


def _devices_response(
    status: str | None = None,
    device_type: str | None = None,
    risk: str | None = None,
    network_id: str | int | None = "current",
) -> dict:
    devices = list_devices(status=status, device_type=device_type, risk=risk, network_id=network_id)
    return {
        "network": str(ALLOWED_NETWORK),
        "current_network": get_current_network(),
        "devices": devices,
        "new_devices": [d for d in devices if d["status"] == "NEW"],
        "counts": get_counts(network_id=network_id),
        "last_scan": get_last_scan(),
        "history": get_network_history(network_id=network_id),
        "topology": build_topology(devices),
        "filters": {
            "status": status,
            "type": device_type,
            "risk": risk,
            "network_id": network_id,
        },
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _autoscan
    import asyncio

    init_db()
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)
    _autoscan = AutoScanManager(SCAN_INTERVAL_SECONDS, _perform_scan)
    set_autoscan_enabled(False)
    yield
    if _autoscan:
        await _autoscan.stop()
        set_autoscan_enabled(False)


app = FastAPI(
    title="Cyber Home Dashboard",
    description="Live local network dashboard",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json(build_snapshot(terminal_line="▸ Conexão live estabelecida"))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)


@app.get("/api/status")
async def api_status():
    return _build_status()


@app.get("/api/networks")
async def api_networks():
    return {"current": get_current_network(), "networks": list_networks()}


@app.get("/api/networks/current")
async def api_current_network():
    return {"network": get_current_network()}


@app.patch("/api/networks/{network_id}")
async def api_patch_network(network_id: int, body: NetworkPatch):
    try:
        updated = update_network(network_id, body.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Rede nao encontrada")
    push_update()
    return {"network": updated}


@app.get("/api/system/status")
async def api_system_status():
    return await asyncio.to_thread(get_system_status)


@app.get("/api/network/health")
async def api_network_health():
    return await asyncio.to_thread(get_network_health)


@app.post("/api/tools/run")
async def api_tools_run(body: SafeToolRequest):
    if body.action not in SAFE_ACTIONS:
        raise HTTPException(status_code=400, detail="acao nao permitida")
    return await asyncio.to_thread(run_safe_action, body.action)


@app.get("/api/history")
async def api_history(limit: int = 48, network_id: str | None = "current"):
    limit = min(max(1, limit), 200)
    try:
        history = get_network_history(limit=limit, network_id=network_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Perfil de rede invalido") from exc
    return {"history": history}


@app.get("/api/topology")
async def api_topology():
    return {
        "network": str(ALLOWED_NETWORK),
        **build_topology(),
    }


@app.patch("/api/topology/positions")
async def api_topology_positions(body: TopologyPositionsPatch):
    if not body.positions:
        raise HTTPException(status_code=400, detail="positions vazio")
    saved = save_positions([p.model_dump() for p in body.positions])
    if saved == 0:
        raise HTTPException(status_code=400, detail="Nenhuma posição válida")
    return {"saved": saved, "topology": build_topology()}


@app.get("/api/devices")
async def api_devices(
    status: str | None = Query(None, description="NEW, ONLINE, OFFLINE"),
    device_type: str | None = Query(
        None, alias="type", description="router, laptop, camera, phone, unknown"
    ),
    risk: str | None = Query(None, description="LOW, MEDIUM, HIGH, CRITICAL"),
    network_id: str | None = Query("current", description="current, all, or numeric network id"),
):
    if status and status.upper() not in ("NEW", "ONLINE", "OFFLINE"):
        raise HTTPException(status_code=400, detail="status inválido")
    if device_type and device_type.lower() not in DEVICE_TYPES:
        raise HTTPException(status_code=400, detail="type inválido")
    if risk and risk.upper() not in RISK_LEVELS:
        raise HTTPException(status_code=400, detail="risk inválido")
    try:
        return _devices_response(
            status=status, device_type=device_type, risk=risk, network_id=network_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Perfil de rede invalido") from exc


@app.get("/api/devices/{device_id}")
async def api_get_device(device_id: int):
    device = get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    return {
        "device": device,
        "ports": describe_ports(device.get("open_ports", [])),
    }


@app.get("/api/devices/{device_id}/changes")
async def api_get_device_changes(device_id: int, limit: int = 50):
    device = get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    limit = min(max(1, limit), 100)
    return {
        "device_id": device_id,
        "ip": device["ip"],
        "changes": list_device_changes(device_id, limit=limit),
    }


@app.get("/api/devices/{device_id}/events")
async def api_get_device_events(device_id: int, limit: int = 20):
    device = get_device_by_id(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    limit = min(max(1, limit), 50)
    return {
        "device_id": device_id,
        "ip": device["ip"],
        "events": get_device_events(device_id, limit=limit),
    }


@app.patch("/api/devices/{device_id}/notes")
async def api_patch_device_notes(device_id: int, body: DeviceNotesPatch):
    updated = update_device_notes(device_id, body.notes)
    if not updated:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    push_terminal(f"▸ Notas salvas: {updated['ip']}")
    push_update()
    return {"device": updated}


@app.get("/api/devices/{device_id}/export.json")
async def api_export_device_json(device_id: int):
    payload = device_export_payload(device_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    device = payload["device"]
    filename = f"device_{device['ip'].replace('.', '_')}.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/devices/{device_id}/trusted")
async def api_mark_device_trusted(device_id: int):
    updated = mark_device_trusted(device_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    push_terminal(f"▸ Marcado como trusted: {updated['ip']}")
    push_update()
    return {"device": updated}


@app.patch("/api/devices/{device_id}")
async def api_patch_device(device_id: int, body: DevicePatch):
    try:
        updated = update_device(
            device_id,
            custom_name=body.custom_name,
            device_type=body.device_type,
            tag=body.tag,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not updated:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    push_terminal(f"▸ Device #{device_id} atualizado")
    push_update()
    return {"device": updated}


@app.get("/api/devices/export.csv")
async def api_export_csv():
    content = devices_to_csv()
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="devices.csv"'},
    )


@app.post("/api/devices/mark-seen")
async def api_mark_seen():
    updated = mark_devices_seen()
    push_terminal(f"▸ {updated} dispositivo(s) marcados como visto")
    push_update()
    return {
        "updated": updated,
        "devices": list_devices(),
        "counts": get_counts(),
    }


@app.get("/api/changes")
async def api_changes(
    acknowledged: bool | None = Query(None),
    limit: int = 100,
):
    limit = min(max(1, limit), 200)
    changes = list_changes(acknowledged=acknowledged, limit=limit)
    return {
        "changes": changes,
        "unacknowledged_count": count_unacknowledged_changes(),
    }


@app.post("/api/changes/{change_id}/ack")
async def api_ack_change(change_id: int):
    updated = acknowledge_change(change_id)
    if not updated:
        raise HTTPException(status_code=404, detail="Mudança não encontrada")
    push_terminal(f"▸ Mudança #{change_id} reconhecida")
    push_update()
    return {"change": updated, "unacknowledged_count": count_unacknowledged_changes()}


@app.get("/api/events")
async def api_events(limit: int = 100, network_id: str | None = Query("current")):
    limit = min(max(1, limit), 500)
    return {"events": list_events(limit=limit, network_id=network_id)}


@app.post("/api/scan")
async def api_scan():
    result = await asyncio.to_thread(_perform_scan)
    result["counts"] = get_counts()
    return result


@app.post("/api/autoscan/start")
async def api_autoscan_start():
    if not _autoscan:
        raise HTTPException(status_code=500, detail="Auto-scan não inicializado")
    await _autoscan.start()
    set_autoscan_enabled(True)
    push_terminal("▸ Auto-scan ATIVADO")
    push_update()
    return _build_status()


@app.post("/api/autoscan/stop")
async def api_autoscan_stop():
    if not _autoscan:
        raise HTTPException(status_code=500, detail="Auto-scan não inicializado")
    await _autoscan.stop()
    set_autoscan_enabled(False)
    push_terminal("▸ Auto-scan DESATIVADO")
    push_update()
    return _build_status()


@app.get("/scan")
async def scan_legacy():
    result = await asyncio.to_thread(_perform_scan)
    result["counts"] = get_counts()
    return result


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "websocket": "/ws/events",
        "topology": "/api/topology",
        "baseline_changes": list(BASELINE_CHANGE_TYPES),
        "device_types": list(DEVICE_TYPES),
        "tags": list(TAGS),
        "risk_levels": list(RISK_LEVELS),
    }


@app.get("/")
async def index():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
