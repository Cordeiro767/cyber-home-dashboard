/* Network Topology — vis-network (v0.6) */

const TopologyMap = (() => {
  const TYPE_ICONS = {
    router: "🌐",
    laptop: "💻",
    camera: "📷",
    phone: "📱",
    unknown: "◆",
  };

  const RISK_COLORS = {
    LOW: { background: "#39ff14", border: "#2bcc10", highlight: "#5fff44" },
    MEDIUM: { background: "#ffe600", border: "#ccb800", highlight: "#fff44d" },
    HIGH: { background: "#ff00aa", border: "#cc0088", highlight: "#ff44cc" },
    CRITICAL: { background: "#ff3355", border: "#cc2244", highlight: "#ff6680" },
  };

  let network = null;
  let nodesDataset = null;
  let edgesDataset = null;
  let container = null;
  let tooltipEl = null;
  let saveTimer = null;
  let initialized = false;

  function riskStyle(risk, isRouter, status) {
    const base = RISK_COLORS[risk] || RISK_COLORS.MEDIUM;
    const offline = status === "OFFLINE";
    return {
      background: offline ? "#2a3540" : base.background,
      border: offline ? "#5a7a99" : base.border,
      highlight: {
        background: base.highlight,
        border: "#00f0ff",
      },
    };
  }

  function glowShadow(risk, isRouter) {
    const colors = {
      LOW: "rgba(57,255,20,0.55)",
      MEDIUM: "rgba(255,230,0,0.5)",
      HIGH: "rgba(255,0,170,0.55)",
      CRITICAL: "rgba(255,51,85,0.85)",
    };
    const size = isRouter ? 22 : risk === "CRITICAL" ? 20 : 14;
    return {
      enabled: true,
      color: colors[risk] || colors.MEDIUM,
      size,
      x: 0,
      y: 0,
    };
  }

  function toVisNode(n) {
    const icon = TYPE_ICONS[n.device_type] || TYPE_ICONS.unknown;
    const short =
      (n.label || n.ip || "?").length > 14
        ? (n.label || n.ip).slice(0, 12) + "…"
        : n.label || n.ip;
    const ping =
      n.latency_ms != null ? `${n.latency_ms} ms` : "—";

    return {
      id: n.id,
      label: `${icon}\n${short}`,
      x: n.x,
      y: n.y,
      size: n.is_router ? 36 : 26,
      shape: "dot",
      color: riskStyle(n.risk, n.is_router, n.status),
      shadow: glowShadow(n.risk, n.is_router),
      font: {
        color: "#c8e6ff",
        size: 11,
        face: "Consolas, monospace",
        multi: true,
      },
      borderWidth: n.is_router ? 3 : 2,
      borderWidthSelected: 4,
      device_id: n.device_id,
      _meta: {
        device_id: n.device_id,
        ip: n.ip,
        hostname: n.hostname,
        vendor: n.vendor,
        latency_ms: n.latency_ms,
        status: n.status,
        risk: n.risk,
        device_type: n.device_type,
        display_name: n.label,
      },
      title: buildTooltipHtml(n, ping),
    };
  }

  function buildTooltipHtml(n, ping) {
    return [
      `IP: ${n.ip}`,
      `Hostname: ${n.hostname}`,
      `Vendor: ${n.vendor}`,
      `Ping: ${ping}`,
      `Status: ${n.status}`,
      `Risco: ${n.risk}`,
    ].join("\n");
  }

  function showRichTooltip(event, meta, ping) {
    if (!tooltipEl || !meta) return;
    tooltipEl.innerHTML = `
      <strong>${meta.display_name || meta.ip}</strong>
      <span class="tt-row"><span>IP</span><span>${meta.ip}</span></span>
      <span class="tt-row"><span>Hostname</span><span>${meta.hostname}</span></span>
      <span class="tt-row"><span>Vendor</span><span>${meta.vendor}</span></span>
      <span class="tt-row"><span>Ping</span><span>${ping}</span></span>
      <span class="tt-row"><span>Status</span><span class="tt-${(meta.status || "").toLowerCase()}">${meta.status}</span></span>
      <span class="tt-row"><span>Risco</span><span class="tt-risk tt-risk-${(meta.risk || "").toLowerCase()}">${meta.risk}</span></span>
    `;
    tooltipEl.classList.remove("hidden");
    const rect = container.getBoundingClientRect();
    tooltipEl.style.left = `${event.clientX - rect.left + 12}px`;
    tooltipEl.style.top = `${event.clientY - rect.top + 12}px`;
  }

  function hideTooltip() {
    tooltipEl?.classList.add("hidden");
  }

  function scheduleSavePositions() {
    if (!network) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      const pos = network.getPositions();
      const positions = Object.entries(pos).map(([node_id, p]) => ({
        node_id,
        x: p.x,
        y: p.y,
      }));
      if (!positions.length) return;
      fetch("/api/topology/positions", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ positions }),
      }).catch(() => {});
    }, 600);
  }

  function init() {
    if (initialized) return;
    container = document.getElementById("topologyNetwork");
    tooltipEl = document.getElementById("topologyTooltip");
    if (!container || typeof vis === "undefined") return;

    nodesDataset = new vis.DataSet([]);
    edgesDataset = new vis.DataSet([]);

    const options = {
      physics: { enabled: false },
      interaction: {
        dragNodes: true,
        dragView: true,
        zoomView: true,
        hover: true,
        tooltipDelay: 80,
      },
      edges: {
        width: 2,
        color: {
          color: "rgba(0, 240, 255, 0.35)",
          highlight: "#00f0ff",
          hover: "#00f0ff",
        },
        smooth: { type: "cubicBezier", roundness: 0.4 },
        shadow: {
          enabled: true,
          color: "rgba(0,240,255,0.25)",
          size: 6,
        },
      },
      nodes: { chosen: { node: () => ({ borderWidth: 4 }) } },
    };

    network = new vis.Network(
      container,
      { nodes: nodesDataset, edges: edgesDataset },
      options
    );

    network.on("dragEnd", scheduleSavePositions);

    network.on("hoverNode", (params) => {
      const node = nodesDataset.get(params.node);
      if (node?._meta) {
        const ping =
          node._meta.latency_ms != null
            ? `${node._meta.latency_ms} ms`
            : "—";
        showRichTooltip(params.event, node._meta, ping);
      }
    });
    network.on("blurNode", hideTooltip);

    network.on("click", (params) => {
      if (!params.nodes.length) return;
      const node = nodesDataset.get(params.nodes[0]);
      const deviceId = node?._meta?.device_id || node?.device_id;
      if (deviceId && typeof DeviceDetails !== "undefined") {
        DeviceDetails.open(deviceId);
      }
    });

    document.getElementById("topologyFit")?.addEventListener("click", () => {
      network?.fit({ animation: { duration: 400, easingFunction: "easeInOutQuad" } });
    });
    document.getElementById("topologyZoomIn")?.addEventListener("click", () => {
      const scale = network.getScale();
      network.moveTo({ scale: scale * 1.25 });
    });
    document.getElementById("topologyZoomOut")?.addEventListener("click", () => {
      const scale = network.getScale();
      network.moveTo({ scale: scale * 0.8 });
    });

    initialized = true;
  }

  function update(topology) {
    init();
    if (!network || !topology?.nodes) return;

    const currentPos = network.getPositions();
    const visNodes = topology.nodes.map((n) => {
      const vn = toVisNode(n);
      if (currentPos[n.id]) {
        vn.x = currentPos[n.id].x;
        vn.y = currentPos[n.id].y;
      }
      return vn;
    });

    const visEdges = (topology.edges || []).map((e, i) => ({
      id: `edge-${i}`,
      from: e.from,
      to: e.to,
      arrows: { to: { enabled: true, scaleFactor: 0.45 } },
    }));

    nodesDataset.clear();
    edgesDataset.clear();
    nodesDataset.add(visNodes);
    edgesDataset.add(visEdges);

    if (!Object.keys(currentPos).length) {
      network.fit({ animation: { duration: 500 } });
    }
  }

  return { init, update, getNetwork: () => network };
})();
