/* Device Details modal — v0.7 */

const DeviceDetails = (() => {
  const modal = () => document.getElementById("deviceDetailsModal");
  let currentId = null;
  let currentDevice = null;

  const EVENT_LABELS = {
    DEVICE_NEW: "NOVO",
    DEVICE_OFFLINE: "OFFLINE",
    DEVICE_BACK_ONLINE: "VOLTOU ONLINE",
    PORT_OPENED: "PORTA ABERTA",
    PORT_CLOSED: "PORTA FECHADA",
    HOSTNAME_CHANGED: "HOSTNAME",
    VENDOR_CHANGED: "VENDOR",
    MAC_CHANGED: "MAC",
    IP_CHANGED: "IP",
  };

  function esc(str) {
    const d = document.createElement("div");
    d.textContent = str ?? "-";
    return d.innerHTML;
  }

  function setTab(name) {
    document.querySelectorAll(".dd-tab").forEach((t) => {
      t.classList.toggle("active", t.dataset.tab === name);
    });
    document.querySelectorAll(".dd-panel").forEach((p) => {
      p.classList.toggle("active", p.id === `ddPanel${name}`);
    });
  }

  function renderOverview(device, ports) {
    const grid = document.getElementById("ddOverviewGrid");
    const ping =
      device.latency_ms != null ? `${device.latency_ms} ms` : "—";
    const fields = [
      ["Nome", device.display_name || device.custom_name || "—"],
      ["custom_name", device.custom_name || "—"],
      ["IP", device.ip],
      ["MAC", device.mac],
      ["Vendor", device.vendor],
      ["Hostname", device.hostname],
      ["Status", device.status],
      ["Tipo", device.device_type],
      ["Tag", device.tag],
      ["Risco", device.risk],
      ["First seen", device.first_seen],
      ["Last seen", device.last_seen],
      ["Ping atual", ping],
    ];
    grid.innerHTML = fields
      .map(
        ([k, v]) => `
      <div class="dd-field">
        <span class="dd-key">${esc(k)}</span>
        <span class="dd-val ${k === "Risco" ? `dd-risk-${(v + "").toLowerCase()}` : ""}">${esc(v)}</span>
      </div>`
      )
      .join("");

    document.getElementById("ddDetailTitle").textContent =
      device.display_name || device.ip;
    document.getElementById("ddDetailSubtitle").textContent =
      `${device.ip} · ${device.risk} · ${device.status}`;

    document.getElementById("ddRenameInput").value = device.custom_name || "";
    document.getElementById("ddTypeSelect").value = device.device_type || "unknown";
    document.getElementById("ddTagSelect").value = device.tag || "unknown";
    document.getElementById("ddNotesInput").value = device.notes || "";

    renderPorts(ports);
  }

  function renderPorts(ports) {
    const el = document.getElementById("ddPortsList");
    if (!ports?.length) {
      el.innerHTML = '<p class="dd-empty">Nenhuma porta aberta registrada no último scan.</p>';
      return;
    }
    el.innerHTML = ports
      .map(
        (p) => `
      <div class="dd-port ${p.sensitive ? "dd-port-sensitive" : ""}">
        <span class="dd-port-num">${p.port}</span>
        <span class="dd-port-svc">${esc(p.service)}</span>
        ${p.sensitive ? '<span class="dd-port-warn">SENSÍVEL</span>' : ""}
      </div>`
      )
      .join("");
  }

  function renderEvents(events) {
    const el = document.getElementById("ddEventsList");
    if (!events?.length) {
      el.innerHTML = '<p class="dd-empty">Nenhum evento para este dispositivo.</p>';
      return;
    }
    el.innerHTML = events
      .map(
        (e) => `
      <div class="dd-event dd-event-${(e.event_type || "").toLowerCase().replace(/_/g, "-")}">
        <div class="dd-event-head">
          <span class="dd-event-type">${EVENT_LABELS[e.event_type] || esc(e.event_type)}</span>
          <time>${esc(e.created_at)}</time>
        </div>
        <p>${esc(e.message)}</p>
      </div>`
      )
      .join("");
  }

  function renderDeviceChanges(changes) {
    const el = document.getElementById("ddChangesList");
    if (!changes?.length) {
      el.innerHTML = '<p class="dd-empty">Sem mudanças registradas para este dispositivo.</p>';
      return;
    }
    el.innerHTML = changes
      .map(
        (c) => `
      <div class="dd-change ${c.acknowledged ? "ack" : "pending"} sev-${(c.severity || "").toLowerCase()}">
        <div class="dd-change-head">
          <span>${EVENT_LABELS[c.change_type] || esc(c.change_type)}</span>
          <span class="dd-change-sev">${esc(c.severity)}</span>
        </div>
        <p class="dd-change-val">${esc(c.old_value)} → ${esc(c.new_value)}</p>
        <time>${esc(c.created_at)}</time>
        ${
          c.acknowledged
            ? ""
            : `<button type="button" class="btn-secondary btn-small dd-ack-btn" data-change-id="${c.id}">Reconhecer</button>`
        }
      </div>`
      )
      .join("");
    el.querySelectorAll(".dd-ack-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = Number(btn.dataset.changeId);
        const res = await fetch(`/api/changes/${id}/ack`, { method: "POST" });
        if (!res.ok) return alert("Falha ao reconhecer");
        await load(currentId);
        if (typeof refreshChangesPanel === "function") refreshChangesPanel();
      });
    });
  }

  async function load(deviceId) {
    const [devRes, evRes, chRes] = await Promise.all([
      fetch(`/api/devices/${deviceId}`),
      fetch(`/api/devices/${deviceId}/events?limit=20`),
      fetch(`/api/devices/${deviceId}/changes?limit=30`),
    ]);
    if (!devRes.ok) throw new Error("Dispositivo não encontrado");
    const devData = await devRes.json();
    const evData = evRes.ok ? await evRes.json() : { events: [] };
    const chData = chRes.ok ? await chRes.json() : { changes: [] };
    currentDevice = devData.device;
    renderOverview(devData.device, devData.ports);
    renderEvents(evData.events);
    renderDeviceChanges(chData.changes);
    return devData.device;
  }

  async function open(deviceId) {
    if (!deviceId) return;
    currentId = deviceId;
    modal()?.classList.remove("hidden");
    document.body.classList.add("modal-open");
    setTab("Overview");
    document.getElementById("ddOverviewGrid").innerHTML =
      '<p class="dd-empty">Carregando…</p>';
    try {
      await load(deviceId);
    } catch (err) {
      document.getElementById("ddOverviewGrid").innerHTML =
        `<p class="dd-empty error">${esc(err.message)}</p>`;
    }
  }

  function close() {
    modal()?.classList.add("hidden");
    document.body.classList.remove("modal-open");
    currentId = null;
    currentDevice = null;
  }

  async function saveRename() {
    if (!currentId) return;
    const res = await fetch(`/api/devices/${currentId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        custom_name: document.getElementById("ddRenameInput").value.trim() || null,
        device_type: document.getElementById("ddTypeSelect").value,
        tag: document.getElementById("ddTagSelect").value,
      }),
    });
    if (!res.ok) throw new Error("Falha ao salvar");
    await load(currentId);
    if (typeof appendTerminal === "function") {
      appendTerminal(`▸ Device #${currentId} atualizado`);
    }
  }

  async function saveNotes() {
    if (!currentId) return;
    const res = await fetch(`/api/devices/${currentId}/notes`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        notes: document.getElementById("ddNotesInput").value,
      }),
    });
    if (!res.ok) throw new Error("Falha ao salvar notas");
    await load(currentId);
  }

  async function markTrusted() {
    if (!currentId) return;
    const res = await fetch(`/api/devices/${currentId}/trusted`, {
      method: "POST",
    });
    if (!res.ok) throw new Error("Falha ao marcar trusted");
    await load(currentId);
  }

  function exportJson() {
    if (!currentId) return;
    window.open(`/api/devices/${currentId}/export.json`, "_blank");
  }

  function bind() {
    document.querySelectorAll(".dd-tab").forEach((tab) => {
      tab.addEventListener("click", () => setTab(tab.dataset.tab));
    });
    document.getElementById("ddCloseBtn")?.addEventListener("click", close);
    document.getElementById("ddSaveMetaBtn")?.addEventListener("click", () =>
      saveRename().catch((e) => alert(e.message))
    );
    document.getElementById("ddSaveNotesBtn")?.addEventListener("click", () =>
      saveNotes().catch((e) => alert(e.message))
    );
    document.getElementById("ddTrustedBtn")?.addEventListener("click", () =>
      markTrusted().catch((e) => alert(e.message))
    );
    document.getElementById("ddExportBtn")?.addEventListener("click", exportJson);
    modal()?.addEventListener("click", (e) => {
      if (e.target === modal()) close();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal()?.classList.contains("hidden")) close();
    });
  }

  bind();
  return { open, close };
})();
