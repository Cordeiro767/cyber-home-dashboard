/* Cyber Home Dashboard v1.0 - live WebSocket + local monitors */

const $ = (id) => document.getElementById(id);

const scanBtn = $("scanBtn");
const autoScanBtn = $("autoScanBtn");
const markSeenBtn = $("markSeenBtn");
const statusEl = $("status");
const tableBody = $("deviceTable");
const alertBanner = $("alertBanner");
const alertText = $("alertText");
const eventsList = $("eventsList");
const changesList = $("changesList");
const changesBadge = $("changesBadge");
const terminalFeed = $("terminalFeed");
const wsIndicator = $("wsIndicator");

const statOnline = $("statOnline");
const statOffline = $("statOffline");
const statNew = $("statNew");
const statTotal = $("statTotal");
const lastScanEl = $("lastScan");

const filterStatus = $("filterStatus");
const filterType = $("filterType");
const filterRisk = $("filterRisk");
const clearFilters = $("clearFilters");
const currentNetworkName = $("currentNetworkName");
const currentNetworkMeta = $("currentNetworkMeta");
const networkSelect = $("networkSelect");
const currentOnlyToggle = $("currentOnlyToggle");
const networkRenameInput = $("networkRenameInput");
const networkRenameBtn = $("networkRenameBtn");
const sysCpu = $("sysCpu");
const sysRam = $("sysRam");
const sysDisk = $("sysDisk");
const sysUptime = $("sysUptime");
const sysTemp = $("sysTemp");
const sysProcesses = $("sysProcesses");
const netStatus = $("netStatus");
const netGateway = $("netGateway");
const netGatewayPing = $("netGatewayPing");
const netInternetPing = $("netInternetPing");
const netAveragePing = $("netAveragePing");
const pingHistory = $("pingHistory");
const safeTerminalOutput = $("safeTerminalOutput");

let ws = null;
let wsReconnectTimer = null;
let fallbackPollTimer = null;
let networkChart = null;
let allDevicesCache = [];
let autoscanEnabled = false;
let knownDeviceIds = new Set();
let currentNetwork = null;
let selectedNetworkId = "current";
let utilityRefreshActive = false;
const TERMINAL_MAX = 80;

const EVENT_LABELS = {
  DEVICE_NEW: { label: "NOVO", className: "evt-new" },
  DEVICE_OFFLINE: { label: "OFFLINE", className: "evt-offline" },
  DEVICE_BACK_ONLINE: { label: "VOLTOU", className: "evt-back" },
};

function setStatus(text, isError = false) {
  statusEl.textContent = text;
  statusEl.classList.toggle("error", isError);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "-";
  return div.innerHTML;
}

function statusBadge(status) {
  const map = {
    NEW: { className: "new", label: "NOVO" },
    ONLINE: { className: "online", label: "ONLINE" },
    OFFLINE: { className: "offline", label: "OFFLINE" },
  };
  const info = map[status] || { className: "offline", label: status };
  return `<span class="badge ${info.className}">${info.label}</span>`;
}

function riskBadge(risk) {
  const cls = (risk || "MEDIUM").toLowerCase();
  return `<span class="risk-badge risk-${cls}">${escapeHtml(risk)}</span>`;
}

function formatLatency(ms) {
  if (ms === null || ms === undefined) return '<span class="ping-na">—</span>';
  const cls = ms < 30 ? "ping-good" : ms < 100 ? "ping-ok" : "ping-slow";
  return `<span class="ping-ms ${cls}">${ms} ms</span>`;
}

function applyFilters(devices) {
  return devices.filter((d) => {
    if (filterStatus.value && d.status !== filterStatus.value) return false;
    if (filterType.value && d.device_type !== filterType.value) return false;
    if (filterRisk.value && d.risk !== filterRisk.value) return false;
    return true;
  });
}

function appendTerminal(line) {
  if (!line) return;
  const ts = new Date().toLocaleTimeString("pt-BR");
  const row = document.createElement("div");
  row.className = "terminal-line";
  row.textContent = `[${ts}] ${line}`;
  terminalFeed.appendChild(row);
  while (terminalFeed.children.length > TERMINAL_MAX) {
    terminalFeed.removeChild(terminalFeed.firstChild);
  }
  terminalFeed.scrollTop = terminalFeed.scrollHeight;
}

function setWsIndicator(connected) {
  wsIndicator.textContent = connected ? "● LIVE" : "● OFFLINE";
  wsIndicator.classList.toggle("ws-on", connected);
  wsIndicator.classList.toggle("ws-off", !connected);
}

function initChart() {
  if (typeof Chart === "undefined") return;
  const ctx = $("networkChart").getContext("2d");
  networkChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Online",
          data: [],
          borderColor: "#39ff14",
          backgroundColor: "rgba(57, 255, 20, 0.12)",
          fill: true,
          tension: 0.35,
        },
        {
          label: "Offline",
          data: [],
          borderColor: "#ff3355",
          backgroundColor: "rgba(255, 51, 85, 0.08)",
          fill: true,
          tension: 0.35,
        },
      ],
    },
    options: {
      responsive: true,
      animation: { duration: 400 },
      plugins: { legend: { labels: { color: "#c8e6ff", font: { family: "Consolas" } } } },
      scales: {
        x: { ticks: { color: "#5a7a99", maxTicksLimit: 8 }, grid: { color: "#1a3a4a" } },
        y: { ticks: { color: "#5a7a99" }, grid: { color: "#1a3a4a" }, beginAtZero: true },
      },
    },
  });
}

function updateChart(history) {
  if (!networkChart || !history?.length) return;
  const labels = history.map((h) => {
    const p = (h.recorded_at || "").split(" ");
    return p[1] ? p[1].replace(" UTC", "") : h.recorded_at;
  });
  networkChart.data.labels = labels;
  networkChart.data.datasets[0].data = history.map((h) => h.online);
  networkChart.data.datasets[1].data = history.map((h) => h.offline);
  networkChart.update("none");
}

function activeNetworkParam() {
  return currentOnlyToggle.checked ? "current" : selectedNetworkId;
}

function renderNetworkProfiles(data) {
  currentNetwork = data.current;
  currentNetworkName.textContent = currentNetwork?.name || "Rede atual";
  currentNetworkMeta.textContent = `${currentNetwork?.subnet || "-"} · gateway ${currentNetwork?.gateway_ip || "-"}${currentNetwork?.ssid ? ` · ${currentNetwork.ssid}` : ""}`;
  networkRenameInput.value = currentNetwork?.name || "";

  const previous = networkSelect.value || "current";
  networkSelect.innerHTML = [
    '<option value="current">Rede atual</option>',
    '<option value="all">Histórico de outras redes</option>',
    ...(data.networks || []).map(
      (n) => `<option value="${n.id}">${escapeHtml(n.name)} (${n.device_count || 0})</option>`
    ),
  ].join("");
  networkSelect.value = [...networkSelect.options].some((o) => o.value === previous) ? previous : "current";
  selectedNetworkId = networkSelect.value;
}

async function refreshNetworkProfiles() {
  try {
    const res = await fetch("/api/networks");
    if (!res.ok) return;
    renderNetworkProfiles(await res.json());
  } catch {
    /* keep dashboard usable without profile controls */
  }
}

function renderStats(counts, lastScan, animate = false) {
  const pulse = (el, val) => {
    if (animate && el.textContent !== String(val)) {
      el.closest(".stat-card")?.classList.add("stat-bump");
      setTimeout(() => el.closest(".stat-card")?.classList.remove("stat-bump"), 500);
    }
    el.textContent = val;
  };
  pulse(statOnline, counts?.online ?? 0);
  pulse(statOffline, counts?.offline ?? 0);
  pulse(statNew, counts?.new ?? 0);
  pulse(statTotal, counts?.total ?? 0);
  lastScanEl.textContent = lastScan || "—";
}

function showAlertFromDevices(devices, events) {
  const newOnes = devices.filter((d) => d.status === "NEW");
  const critical = devices.filter((d) => d.risk === "CRITICAL");
  const recentOffline = (events || []).filter((e) => e.event_type === "DEVICE_OFFLINE").slice(0, 2);
  const parts = [];
  if (critical.length) parts.push(`CRÍTICO: ${critical.map((d) => d.ip).join(", ")}`);
  if (newOnes.length) parts.push(`Novos: ${newOnes.map((d) => d.ip).join(", ")}`);
  if (recentOffline.length) parts.push(`Offline: ${recentOffline.map((e) => e.ip).join(", ")}`);

  if (parts.length) {
    alertText.textContent = parts.join(" · ");
    alertBanner.classList.remove("hidden");
    alertBanner.classList.toggle("alert-offline", critical.length > 0);
    alertBanner.classList.toggle("alert-new", !critical.length && newOnes.length > 0);
  } else {
    alertBanner.classList.add("hidden");
  }
}

function renderDevices(devices) {
  const filtered = applyFilters(devices);
  if (!filtered.length) {
    tableBody.innerHTML = '<tr><td colspan="8" class="empty">Nenhum dispositivo neste filtro.</td></tr>';
    return;
  }

  const currentIds = new Set(filtered.map((d) => d.id));

  tableBody.innerHTML = filtered
    .map((d) => {
      const isNewId = !knownDeviceIds.has(d.id);
      const rowClass = [
        d.risk === "CRITICAL" ? "row-critical-pulse" : "",
        d.status === "NEW" ? "row-new" : "",
        d.status === "OFFLINE" ? "row-offline" : "",
        isNewId ? "row-flash" : "",
      ]
        .filter(Boolean)
        .join(" ");

      const sub = d.custom_name ? `<small class="sub-host">${escapeHtml(d.hostname)}</small>` : "";

      return `
        <tr class="${rowClass} row-clickable" data-id="${d.id}" title="Clique para detalhes">
          <td><strong>${escapeHtml(d.display_name)}</strong>${sub}</td>
          <td class="mono">${escapeHtml(d.ip)}</td>
          <td>${formatLatency(d.latency_ms)}</td>
          <td>${escapeHtml(d.device_type)}</td>
          <td><span class="tag-pill tag-${escapeHtml(d.tag)}">${escapeHtml(d.tag)}</span></td>
          <td>${statusBadge(d.status)}</td>
          <td>${riskBadge(d.risk)}</td>
          <td><button type="button" class="btn-edit" data-id="${d.id}">Detalhes</button></td>
        </tr>
      `;
    })
    .join("");

  filtered.forEach((d) => knownDeviceIds.add(d.id));
  currentIds.forEach((id) => knownDeviceIds.add(id));

  tableBody.querySelectorAll("tr.row-clickable").forEach((row) => {
    row.addEventListener("click", (e) => {
      if (e.target.closest(".btn-edit")) {
        e.stopPropagation();
      }
      DeviceDetails.open(Number(row.dataset.id));
    });
  });
  tableBody.querySelectorAll(".btn-edit").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      DeviceDetails.open(Number(btn.dataset.id));
    });
  });
}

const CHANGE_LABELS = {
  PORT_OPENED: "PORTA +",
  PORT_CLOSED: "PORTA −",
  HOSTNAME_CHANGED: "HOSTNAME",
  VENDOR_CHANGED: "VENDOR",
  MAC_CHANGED: "MAC",
  IP_CHANGED: "IP",
};

function updateChangesBadge(count) {
  const n = count ?? 0;
  if (n > 0) {
    changesBadge.textContent = String(n);
    changesBadge.classList.remove("hidden");
  } else {
    changesBadge.classList.add("hidden");
  }
}

function renderChanges(changes, unackCount) {
  updateChangesBadge(unackCount ?? changes?.filter((c) => !c.acknowledged).length ?? 0);
  const pending = (changes || []).filter((c) => !c.acknowledged);
  const list = pending.length ? pending : changes || [];
  if (!list.length) {
    changesList.innerHTML =
      '<li class="empty-event">Nenhuma mudança pendente.</li>';
    return;
  }
  changesList.innerHTML = list
    .map(
      (c) => `
    <li class="change-item sev-${(c.severity || "").toLowerCase()} ${c.acknowledged ? "ack" : ""}" data-device-id="${c.device_id}">
      <div class="change-head">
        <span class="change-type">${CHANGE_LABELS[c.change_type] || escapeHtml(c.change_type)}</span>
        <span class="change-sev">${escapeHtml(c.severity)}</span>
      </div>
      <p class="change-device">${escapeHtml(c.display_name || c.ip)} · ${escapeHtml(c.ip)}</p>
      <p class="change-val">${escapeHtml(c.old_value || "—")} → ${escapeHtml(c.new_value || "—")}</p>
      <time>${escapeHtml(c.created_at)}</time>
      ${
        c.acknowledged
          ? ""
          : `<button type="button" class="btn-secondary btn-small change-ack-btn" data-id="${c.id}">Reconhecer mudança</button>`
      }
    </li>`
    )
    .join("");

  changesList.querySelectorAll(".change-ack-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const id = Number(btn.dataset.id);
      try {
        const res = await fetch(`/api/changes/${id}/ack`, { method: "POST" });
        if (!res.ok) throw new Error("Falha");
        const data = await res.json();
        await refreshChangesPanel();
        if (typeof appendTerminal === "function") {
          appendTerminal(`▸ Mudança #${id} reconhecida`);
        }
      } catch {
        setStatus("Falha ao reconhecer mudança.", true);
      }
    });
  });

  changesList.querySelectorAll(".change-item").forEach((li) => {
    li.style.cursor = "pointer";
    li.addEventListener("click", (e) => {
      if (e.target.closest(".change-ack-btn")) return;
      const deviceId = Number(li.dataset.deviceId);
      if (deviceId) DeviceDetails.open(deviceId);
    });
  });
}

async function refreshChangesPanel() {
  try {
    const res = await fetch("/api/changes?acknowledged=false&limit=50");
    if (!res.ok) return;
    const data = await res.json();
    renderChanges(data.changes, data.unacknowledged_count);
  } catch {
    /* ignore */
  }
}

window.refreshChangesPanel = refreshChangesPanel;

function renderEvents(events) {
  if (!events?.length) {
    eventsList.innerHTML = '<li class="empty-event">Nenhum evento.</li>';
    return;
  }
  eventsList.innerHTML = events
    .map((e) => {
      const info = EVENT_LABELS[e.event_type] || { label: e.event_type, className: "" };
      return `
        <li class="event-item ${info.className} event-flash">
          <div class="event-head">
            <span class="event-badge">${info.label}</span>
            <span class="event-ip">${escapeHtml(e.ip)}</span>
          </div>
          <p class="event-msg">${escapeHtml(e.message)}</p>
          <time class="event-time">${escapeHtml(e.created_at)}</time>
        </li>
      `;
    })
    .join("");
}

function updateAutoScanButton(enabled) {
  autoscanEnabled = enabled;
  autoScanBtn.textContent = enabled ? "AUTO-SCAN: ON" : "AUTO-SCAN: OFF";
  autoScanBtn.classList.toggle("active", enabled);
}

function handleSnapshot(data, animate = true) {
  allDevicesCache = data.devices || [];
  renderStats(data.counts, data.last_scan, animate);
  renderDevices(allDevicesCache);
  renderEvents(data.events);
  updateChart(data.history);
  if (data.topology) TopologyMap.update(data.topology);
  renderChanges(data.changes, data.unacknowledged_changes);
  showAlertFromDevices(allDevicesCache, data.events);
  if (data.autoscan) updateAutoScanButton(data.autoscan.enabled);
  if (data.scanning) setStatus("Scan em andamento…");
}

function handleWsMessage(msg) {
  if (msg.type === "terminal" && msg.terminal_line) {
    appendTerminal(msg.terminal_line);
    return;
  }
  if (msg.terminal_line) appendTerminal(msg.terminal_line);
  if (msg.type === "snapshot" || msg.devices) {
    handleSnapshot(msg, true);
    if (!msg.scanning) setStatus("Live · dados atualizados");
  }
}

function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;

  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws/events`);

  ws.onopen = () => {
    setWsIndicator(true);
    setStatus("WebSocket conectado · live");
    if (fallbackPollTimer) {
      clearInterval(fallbackPollTimer);
      fallbackPollTimer = null;
    }
  };

  ws.onmessage = (ev) => {
    try {
      handleWsMessage(JSON.parse(ev.data));
    } catch {
      appendTerminal("▸ Erro ao parsear mensagem WS");
    }
  };

  ws.onclose = () => {
    setWsIndicator(false);
    setStatus("WebSocket desconectado · reconectando…", true);
    ws = null;
    if (!fallbackPollTimer) {
      fallbackPollTimer = setInterval(refreshFallback, 15000);
    }
    wsReconnectTimer = setTimeout(connectWebSocket, 3000);
  };

  ws.onerror = () => ws?.close();
}

async function refreshFallback() {
  try {
    const networkParam = activeNetworkParam();
    const [devRes, statusRes, topoRes] = await Promise.all([
      fetch(`/api/devices?network_id=${encodeURIComponent(networkParam)}`),
      fetch("/api/status"),
      fetch("/api/topology"),
    ]);
    const dev = await devRes.json();
    const st = await statusRes.json();
    const topo = await topoRes.json();
    handleSnapshot({
      ...dev,
      counts: dev.counts || st.counts,
      last_scan: st.last_scan,
      scanning: st.scanning,
      autoscan: st.autoscan,
      history: dev.history,
      topology: networkParam === "current" ? topo : dev.topology,
    }, false);
  } catch {
    setStatus("Backend indisponível", true);
  }
}

async function runScan() {
  scanBtn.disabled = true;
  setStatus("Escaneando…");
  try {
    const res = await fetch("/api/scan", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    await refreshNetworkProfiles();
    handleSnapshot({ ...data, counts: data.counts || (await fetch("/api/status")).counts }, true);
    setStatus(data.error ? `Erro: ${data.error}` : "Scan solicitado.", !!data.error);
  } catch (err) {
    setStatus(`Falha: ${err.message}`, true);
  } finally {
    scanBtn.disabled = false;
  }
}

async function toggleAutoScan() {
  autoScanBtn.disabled = true;
  try {
    const endpoint = autoscanEnabled ? "/api/autoscan/stop" : "/api/autoscan/start";
    const res = await fetch(endpoint, { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    updateAutoScanButton(data.autoscan?.enabled);
    setStatus(data.autoscan?.enabled ? "Auto-scan ON" : "Auto-scan OFF");
  } catch (err) {
    setStatus(`Falha: ${err.message}`, true);
  } finally {
    autoScanBtn.disabled = false;
  }
}

async function markSeen() {
  markSeenBtn.disabled = true;
  try {
    const res = await fetch("/api/devices/mark-seen", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    setStatus("Marcado — aguardando live update…");
  } catch (err) {
    setStatus(`Falha: ${err.message}`, true);
  } finally {
    markSeenBtn.disabled = false;
  }
}

async function renameCurrentNetwork() {
  if (!currentNetwork?.id) return;
  const name = networkRenameInput.value.trim();
  if (!name) return;
  networkRenameBtn.disabled = true;
  try {
    const res = await fetch(`/api/networks/${currentNetwork.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await refreshNetworkProfiles();
    setStatus("Rede renomeada.");
  } catch (err) {
    setStatus(`Falha ao renomear rede: ${err.message}`, true);
  } finally {
    networkRenameBtn.disabled = false;
  }
}

function formatMs(value) {
  return value === null || value === undefined ? "--" : `${value} ms`;
}

function renderSystemStatus(data) {
  sysCpu.textContent = `${data.cpu_percent}%`;
  sysRam.textContent = `${data.ram.percent}%`;
  sysDisk.textContent = `${data.disk.percent}%`;
  sysUptime.textContent = data.uptime || "--";
  sysTemp.textContent = data.temperature_available
    ? `Temp: ${data.temperatures.map((t) => `${t.label} ${t.current_c}C`).join(" | ")}`
    : "Temp: indisponivel no Windows";
  sysProcesses.innerHTML = (data.top_processes || [])
    .map(
      (p) =>
        `<li><span>${escapeHtml(p.name)}</span><strong>${p.cpu_percent}% / ${p.memory_mb} MB</strong></li>`
    )
    .join("");
}

function renderNetworkHealth(data) {
  netStatus.textContent = data.status;
  netStatus.className = `internet-status status-${(data.status || "").toLowerCase()}`;
  netGateway.textContent = data.gateway || "--";
  netGatewayPing.textContent = formatMs(data.gateway_ping?.latency_ms);
  netInternetPing.textContent = formatMs(data.internet_ping?.latency_ms);
  netAveragePing.textContent = formatMs(data.average_latency_ms);
  pingHistory.innerHTML = (data.history || [])
    .slice(-60)
    .map((point) => {
      const value = point.internet_ms ?? point.gateway_ms;
      const height = value === null || value === undefined ? 8 : Math.min(42, Math.max(8, 42 - value / 4));
      return `<span class="ping-bar status-${(point.status || "").toLowerCase()}" style="height:${height}px" title="${escapeHtml(point.status)} ${formatMs(value)}"></span>`;
    })
    .join("");
}

async function refreshUtilityPanels() {
  if (utilityRefreshActive) return;
  utilityRefreshActive = true;
  try {
    const [sysRes, netRes] = await Promise.all([
      fetch("/api/system/status"),
      fetch("/api/network/health"),
    ]);
    if (sysRes.ok) renderSystemStatus(await sysRes.json());
    if (netRes.ok) renderNetworkHealth(await netRes.json());
  } catch {
    appendTerminal("> Falha ao atualizar monitores locais");
  } finally {
    utilityRefreshActive = false;
  }
}

async function runSafeCommand(action, button) {
  button.disabled = true;
  safeTerminalOutput.textContent = `> executando ${action}...`;
  try {
    const res = await fetch("/api/tools/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    safeTerminalOutput.textContent = `> ${data.label}\n\n${data.output || "(sem saida)"}`;
  } catch (err) {
    safeTerminalOutput.textContent = `> erro\n\n${err.message}`;
  } finally {
    button.disabled = false;
  }
}

scanBtn.addEventListener("click", runScan);
autoScanBtn.addEventListener("click", toggleAutoScan);
markSeenBtn.addEventListener("click", markSeen);
networkSelect.addEventListener("change", () => {
  selectedNetworkId = networkSelect.value;
  if (selectedNetworkId !== "current") currentOnlyToggle.checked = false;
  refreshFallback();
});
currentOnlyToggle.addEventListener("change", () => refreshFallback());
networkRenameBtn.addEventListener("click", renameCurrentNetwork);
document.querySelectorAll(".safe-cmd").forEach((btn) => {
  btn.addEventListener("click", () => runSafeCommand(btn.dataset.action, btn));
});
filterStatus.addEventListener("change", () => renderDevices(allDevicesCache));
filterType.addEventListener("change", () => renderDevices(allDevicesCache));
filterRisk.addEventListener("change", () => renderDevices(allDevicesCache));
clearFilters.addEventListener("click", () => {
  filterStatus.value = "";
  filterType.value = "";
  filterRisk.value = "";
  renderDevices(allDevicesCache);
});
initChart();
TopologyMap.init();
appendTerminal("> Cyber Home Dashboard v1.0 boot");
connectWebSocket();
refreshNetworkProfiles();
refreshFallback();
refreshUtilityPanels();
setInterval(refreshUtilityPanels, 3000);
