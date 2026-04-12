const launchBtn = document.getElementById("launchBtn");
const ideaInput = document.getElementById("ideaInput");
const statusEl = document.getElementById("systemStatus");
const wsStatusEl = document.getElementById("wsStatus");
const feedEl = document.getElementById("messageFeed");
const outputEl = document.getElementById("outputs");
const cardsEl = document.getElementById("agentCards");
const phaseTrackEl = document.getElementById("phaseTrack");
const phaseLabelEl = document.getElementById("phaseLabel");
const timelineEmptyEl = document.getElementById("timelineEmpty");
const timelineFiltersEl = document.getElementById("timelineFilters");
const autoScrollToggleEl = document.getElementById("autoScrollToggle");
const timelineTemplate = document.getElementById("timelineItemTemplate");
const outputTemplate = document.getElementById("outputCardTemplate");

// Modal elements
const traceModalEl = document.getElementById("traceModal");
const traceModalBgEl = document.getElementById("traceModalBg");
const closeTraceBtn = document.getElementById("closeTraceBtn");
const traceAgentNameEl = document.getElementById("traceAgentName");
const traceProviderEl = document.getElementById("traceProvider");
const traceModelEl = document.getElementById("traceModel");
const traceSystemPromptEl = document.getElementById("traceSystemPrompt");
const traceUserPromptEl = document.getElementById("traceUserPrompt");
const traceResponseEl = document.getElementById("traceResponse");

const agents = ["ceo", "product", "engineer", "marketing"];
const phaseOrder = ["decomposition", "product", "engineering", "marketing", "complete"];
const phaseLabels = {
  decomposition: "Decomposition",
  product: "Product",
  engineering: "Engineering",
  marketing: "Marketing",
  complete: "Complete"
};

const uiState = {
  selectedFilter: "all",
  timeline: [],
  outputs: {},
  currentPhase: "decomposition",
  runStatus: "Idle",
  agents: {},
  traces: { ceo: [], product: [], engineer: [], marketing: [] }
};

agents.forEach((agent) => {
  uiState.agents[agent] = { status: "waiting", lastAction: "No activity yet" };
});

function titleCase(value) {
  return String(value || "")
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function relativeTime(iso) {
  if (!iso) return "now";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "now";
  const seconds = Math.max(0, Math.floor((Date.now() - parsed.getTime()) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const mins = Math.floor(seconds / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return parsed.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function statusClass(status) {
  if (status === "working") return "is-working";
  if (status === "needs_revision") return "is-needs_revision";
  if (["done", "done_with_warnings"].includes(status)) return `is-${status}`;
  return "";
}

function chipText(status) {
  return titleCase(status || "waiting");
}

function formatValue(value) {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    const text = JSON.stringify(value);
    if (!text) return "N/A";
    return text.length > 220 ? `${text.slice(0, 217)}...` : text;
  } catch {
    return String(value);
  }
}

function normalizeEvent(raw) {
  const type = raw?.event_type || "message_sent";

  if (type === "message_sent") {
    const d = raw.data || {};
    return {
      type,
      ts: d.timestamp || raw.timestamp,
      messageType: d.message_type || "confirmation",
      title: `${titleCase(d.from_agent)} -> ${titleCase(d.to_agent)}`,
      detail: summarizePayload(d.payload),
      meta: `${titleCase(d.from_agent)} to ${titleCase(d.to_agent)}`,
      fromAgent: d.from_agent,
      toAgent: d.to_agent
    };
  }

  if (type === "agent_status_change") {
    const status = raw.data?.status || "updated";
    return {
      type,
      ts: raw.timestamp,
      messageType: "system",
      title: `${titleCase(raw.agent)} status: ${chipText(status)}`,
      detail: raw.data?.note || "Agent status updated.",
      meta: "Status update",
      fromAgent: raw.agent
    };
  }

  if (type === "action_completed") {
    return {
      type,
      ts: raw.timestamp,
      messageType: "system",
      title: `${titleCase(raw.agent)} completed action`,
      detail: summarizePayload(raw.data),
      meta: "Action completed",
      fromAgent: raw.agent
    };
  }

  if (type === "system_complete") {
    return {
      type,
      ts: raw.timestamp,
      messageType: "system",
      title: "System run completed",
      detail: raw.data?.status || "Completed",
      meta: "Final event",
      fromAgent: raw.agent
    };
  }

  return {
    type,
    ts: raw.timestamp,
    messageType: "system",
    title: "Unknown event",
    detail: summarizePayload(raw.data || raw),
    meta: "Unclassified"
  };
}

function summarizePayload(payload) {
  if (!payload) return "No payload";
  if (typeof payload === "string") return payload;

  if (payload.status && payload.error) {
    return `${payload.status}: ${payload.error}`;
  }
  if (payload.feedback) return `Feedback: ${formatValue(payload.feedback)}`;
  if (payload.task) return `Task: ${formatValue(payload.task)}`;
  if (payload.pr_url || payload.issue_url) {
    const bits = [];
    if (payload.pr_url) bits.push("PR ready");
    if (payload.issue_url) bits.push("Issue ready");
    return bits.join(" | ");
  }

  const keys = Object.keys(payload).slice(0, 3);
  if (!keys.length) return "Payload received";
  return `Fields: ${keys.join(", ")}`;
}

function renderAgentCards() {
  cardsEl.innerHTML = "";
  agents.forEach((agent) => {
    const data = uiState.agents[agent];
    const card = document.createElement("article");
    // Add hover styles and cursor pointer
    card.className = `agent-card ${statusClass(data.status)} cursor-pointer hover:ring-2 hover:ring-cyan-500/50 transition-all duration-200`;
    card.title = "Click to view LLM inner thoughts";
    card.innerHTML = `
      <div class="mb-2 flex items-center justify-between gap-2">
        <h3 class="text-sm font-semibold text-slate-100">${titleCase(agent)}</h3>
        <span class="agent-status-chip">${chipText(data.status)}</span>
      </div>
      <p class="line-clamp-2 text-xs text-slate-300">${data.lastAction || "No activity yet"}</p>
    `;
    card.addEventListener("click", () => showTraceModal(agent));
    cardsEl.appendChild(card);
  });
}

function showTraceModal(agent) {
  const agentTraces = uiState.traces[agent];
  if (!agentTraces || agentTraces.length === 0) {
    alert(`No LLM traces available yet for ${titleCase(agent)}.`);
    return;
  }
  const latestTrace = agentTraces[agentTraces.length - 1];
  
  traceAgentNameEl.textContent = titleCase(agent);
  traceProviderEl.textContent = latestTrace.provider;
  traceModelEl.textContent = latestTrace.model;
  traceSystemPromptEl.textContent = latestTrace.system_prompt;
  traceUserPromptEl.textContent = latestTrace.user_prompt;
  
  let formatted = latestTrace.response;
  if (typeof formatted === "object") {
    formatted = JSON.stringify(formatted, null, 2);
  }
  traceResponseEl.textContent = formatted;
  
  traceModalEl.classList.remove("hidden");
}

function closeTraceModal() {
  traceModalEl.classList.add("hidden");
}

if (closeTraceBtn) closeTraceBtn.addEventListener("click", closeTraceModal);
if (traceModalBgEl) traceModalBgEl.addEventListener("click", closeTraceModal);

function renderTimeline() {
  feedEl.innerHTML = "";

  const filtered = uiState.timeline.filter((item) => {
    if (uiState.selectedFilter === "all") return true;
    return item.messageType === uiState.selectedFilter;
  });

  timelineEmptyEl.style.display = filtered.length ? "none" : "block";

  filtered.forEach((item) => {
    const fragment = timelineTemplate.content.cloneNode(true);
    const article = fragment.querySelector(".timeline-item");
    const badge = fragment.querySelector(".event-badge");
    const meta = fragment.querySelector(".event-meta");
    const title = fragment.querySelector(".event-title");
    const details = fragment.querySelector(".event-details");

    badge.textContent = titleCase(item.messageType);
    badge.className = `event-badge badge-${item.messageType}`;
    meta.textContent = `${item.meta} • ${relativeTime(item.ts)}`;
    title.textContent = item.title;
    details.textContent = item.detail;

    article.classList.add("pulse");
    feedEl.prepend(fragment);
  });

  if (autoScrollToggleEl.checked && feedEl.firstElementChild) {
    feedEl.firstElementChild.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function renderOutputs() {
  outputEl.innerHTML = "";
  const keys = Object.keys(uiState.outputs);

  if (!keys.length) {
    outputEl.innerHTML = `
      <div class="rounded-xl border border-dashed border-white/20 bg-slate-900/20 p-5 text-sm text-slate-300">
        Waiting for PR, issue, and final summary.
      </div>
    `;
    return;
  }

  keys.forEach((key) => {
    const fragment = outputTemplate.content.cloneNode(true);
    const labelEl = fragment.querySelector(".output-label");
    const bodyEl = fragment.querySelector(".output-body");

    labelEl.textContent = titleCase(key);
    bodyEl.innerHTML = uiState.outputs[key];

    outputEl.appendChild(fragment);
  });
}

function phaseIndex(name) {
  const lookup = {
    decomposition: 0,
    product: 1,
    engineering: 2,
    marketing: 3,
    complete: 4
  };
  return lookup[name] ?? 0;
}

function updatePhase() {
  const a = uiState.agents;

  if (uiState.runStatus.toLowerCase().includes("complete") || uiState.runStatus.toLowerCase().includes("completed")) {
    uiState.currentPhase = "complete";
  } else if (a.marketing?.status === "working" || a.marketing?.status === "done") {
    uiState.currentPhase = "marketing";
  } else if (a.engineer?.status === "working" || a.engineer?.status === "done") {
    uiState.currentPhase = "engineering";
  } else if (a.product?.status === "working" || a.product?.status === "done") {
    uiState.currentPhase = "product";
  } else {
    uiState.currentPhase = "decomposition";
  }
}

function renderRunStatus() {
  updatePhase();

  statusEl.textContent = uiState.runStatus;
  statusEl.className = "status-pill ";

  const lowered = uiState.runStatus.toLowerCase();
  if (lowered.includes("complete") || lowered.includes("completed")) {
    statusEl.classList.add("status-complete");
  } else if (lowered.includes("fail") || lowered.includes("error")) {
    statusEl.classList.add("status-error");
  } else if (lowered.includes("running") || lowered.includes("working") || lowered.includes("started")) {
    statusEl.classList.add("status-running");
  } else {
    statusEl.classList.add("status-neutral");
  }

  phaseTrackEl.innerHTML = "";
  const current = phaseIndex(uiState.currentPhase);
  phaseOrder.forEach((step, idx) => {
    const node = document.createElement("div");
    node.className = "phase-step";
    if (idx < current) node.classList.add("done");
    if (idx === current) node.classList.add("active");
    node.textContent = phaseLabels[step];
    phaseTrackEl.appendChild(node);
  });
  phaseLabelEl.textContent = `Current: ${phaseLabels[uiState.currentPhase]}`;
}

function updateAgentState(event) {
  if (event.type === "message_sent") {
    const d = event.rawData;
    if (!d || !d.from_agent) return;
    const agent = d.from_agent;
    if (!uiState.agents[agent]) return;
    uiState.agents[agent].lastAction = `${titleCase(d.message_type)} sent to ${titleCase(d.to_agent)}`;
    if (d.message_type === "revision_request" && uiState.agents[d.to_agent]) {
      uiState.agents[d.to_agent].status = "needs_revision";
    }
  }

  if (event.type === "agent_status_change") {
    const agent = event.agent;
    if (!uiState.agents[agent]) return;
    uiState.agents[agent].status = event.data?.status || "updated";
    uiState.agents[agent].lastAction = event.data?.note || uiState.agents[agent].lastAction;
  }

  if (event.type === "action_completed" && uiState.agents[event.agent]) {
    uiState.agents[event.agent].status = "done";
    uiState.agents[event.agent].lastAction = summarizePayload(event.data || { status: "completed" });
  }

  if (event.type === "system_complete") {
    uiState.runStatus = titleCase(event.data?.status || "completed");
    uiState.currentPhase = "complete";
  }
}

function pushTimeline(rawEvent) {
  const normalized = normalizeEvent(rawEvent);
  uiState.timeline.push(normalized);
  if (uiState.timeline.length > 300) uiState.timeline.shift();
}

function setOutputCard(key, valueHtml) {
  uiState.outputs[key] = valueHtml;
}

function handleSystemComplete(data) {
  launchBtn.disabled = false;
  if ((data.status || "").toLowerCase() === "failed") {
    const reason = formatValue(data.reason || "Unknown failure");
    const details = formatValue(data.details || "No details provided.");
    setOutputCard("failure_reason", `<strong>${reason}</strong>`);
    setOutputCard("failure_details", `<pre style="white-space:pre-wrap;word-break:break-word;margin:0;">${details}</pre>`);
  }

  if (data.pr_url) {
    setOutputCard("pr_url", `<a href="${data.pr_url}" target="_blank" rel="noreferrer">Open Pull Request</a>`);
  }
  if (data.issue_url) {
    setOutputCard("issue_url", `<a href="${data.issue_url}" target="_blank" rel="noreferrer">Open GitHub Issue</a>`);
  }
  if (data.final_summary) {
    setOutputCard("final_summary", String(data.final_summary).replace(/\n/g, "<br/>"));
  }
}

function resetRunState() {
  uiState.timeline = [];
  uiState.outputs = {};
  uiState.runStatus = "Running";
  uiState.currentPhase = "decomposition";
  uiState.traces = { ceo: [], product: [], engineer: [], marketing: [] };

  agents.forEach((agent) => {
    uiState.agents[agent] = { status: "waiting", lastAction: "No activity yet" };
  });

  uiState.agents.ceo.status = "working";
  uiState.agents.ceo.lastAction = "Preparing decomposition tasks";
}

function processEvent(event) {
  const normalized = normalizeEvent(event);
  normalized.rawData = event.data || {};
  normalized.type = event.event_type || normalized.type;
  normalized.agent = event.agent;
  normalized.data = event.data || {};

  updateAgentState(normalized);
  pushTimeline(event);

  if (event.event_type === "system_complete") {
    handleSystemComplete(event.data || {});
  }

  renderAgentCards();
  renderTimeline();
  renderOutputs();
  renderRunStatus();
}

function setupFilters() {
  timelineFiltersEl.querySelectorAll("button[data-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      uiState.selectedFilter = btn.dataset.filter;
      timelineFiltersEl.querySelectorAll("button[data-filter]").forEach((x) => x.classList.remove("active"));
      btn.classList.add("active");
      renderTimeline();
    });
  });
}

function setupLaunch() {
  launchBtn.addEventListener("click", async () => {
    launchBtn.disabled = true;
    resetRunState();
    renderAgentCards();
    renderTimeline();
    renderOutputs();
    renderRunStatus();

    try {
      const response = await fetch("/api/launch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ startup_idea: ideaInput.value })
      });
      const data = await response.json();
      const launchStatus = data.status || "unknown";
      if (launchStatus !== "started") {
          uiState.runStatus = titleCase(launchStatus);
          launchBtn.disabled = false;
      } else {
          uiState.runStatus = titleCase(launchStatus);
      }

      processEvent({
        event_type: "message_sent",
        data: {
          timestamp: new Date().toISOString(),
          from_agent: "ceo",
          to_agent: "product",
          message_type: "task",
          payload: { task: `Launch request accepted: ${launchStatus}` }
        }
      });
    } catch (error) {
      uiState.runStatus = "Error";
      launchBtn.disabled = false;
      processEvent({
        event_type: "system_complete",
        agent: "ceo",
        timestamp: new Date().toISOString(),
        data: { status: "failed", final_summary: `Launch request failed: ${error.message}` }
      });
    }
  });
}

function setupWebSocket() {
  const wsProto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${wsProto}://${window.location.host}/ws`);

  ws.onopen = () => {
    wsStatusEl.textContent = "WebSocket: Connected";
    wsStatusEl.className = "status-pill status-complete";
  };

  ws.onclose = () => {
    wsStatusEl.textContent = "WebSocket: Disconnected";
    wsStatusEl.className = "status-pill status-error";
  };

  ws.onerror = () => {
    wsStatusEl.textContent = "WebSocket: Error";
    wsStatusEl.className = "status-pill status-error";
  };

  ws.onmessage = (event) => {
    let parsed;
    try {
      parsed = JSON.parse(event.data);
    } catch {
      parsed = {
        event_type: "message_sent",
        data: {
          message_type: "confirmation",
          from_agent: "ceo",
          to_agent: "ceo",
          timestamp: new Date().toISOString(),
          payload: { raw: "Unparseable websocket payload" }
        }
      };
    }

    if (parsed.event_type === "llm_trace") {
      if (uiState.traces[parsed.agent]) {
        uiState.traces[parsed.agent].push(parsed.data);
      }
      return; // Do not process trace events as timeline events
    }

    if (parsed.event_type === "system_complete") {
      uiState.runStatus = titleCase(parsed.data?.status || "completed");
    } else if (["message_sent", "agent_status_change", "action_completed"].includes(parsed.event_type)) {
      if (uiState.runStatus === "Idle") uiState.runStatus = "Running";
    }

    processEvent(parsed);
  };
}

function init() {
  renderAgentCards();
  renderTimeline();
  renderOutputs();
  renderRunStatus();
  setupFilters();
  setupLaunch();
  setupWebSocket();
}

init();
