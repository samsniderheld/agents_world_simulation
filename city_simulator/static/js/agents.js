"use strict";

// ======================================================================
// Agents -- no tab of their own anymore: agents render as a second
// marker layer on the shared city map (see history.js's redrawCityMap(),
// citymap.js's buildCityMap()), and their combined activity log lives on
// the Logs tab. This file owns: the roster/settings modal, feeding agent
// markers into the shared map, the agent detail modal (with the same
// image/video generation controls a place gets), the treatment plate,
// and the Logs tab's Agent Activity panel.
// ======================================================================

const KIND_META = {
  plan:          { label: 'PLAN',      color: '#60a5fa' },
  decompose:     { label: 'DECOMP',    color: '#3b82f6' },
  observe:       { label: 'OBSERVES',  color: '#22d3ee' },
  react:         { label: 'REACTS',    color: '#e879f9' },
  continue:      { label: 'CONTINUES', color: '#6b7280' },
  memory:        { label: 'MEMORY',    color: '#9ca3af' },
  focal:         { label: 'FOCAL',     color: '#fbbf24' },
  insight:       { label: 'INSIGHT',   color: '#f59e0b' },
  action:        { label: 'ACTION',    color: '#e5e7eb' },
  dialogue:      { label: 'DIALOGUE',  color: '#4ade80' },
  reflect_pause: { label: 'REFLECT',   color: '#a78bfa' },
};

const aState = {
  agents: [],              // current run's agents (name/color/age/traits/location)
  roster: [],               // every agent available to pick from
  selectedAgents: new Set(),
  lastStartedAt: null,      // detects a new/changed run
  lastPhase: null,
  lastAgentsSignature: null, // name@location per agent -- redraw the map only when this changes
  treatment: null,
};

const statusPill = document.getElementById('agentsStatusPill');
const statusText = document.getElementById('agentsStatusText');
const errorMsg = document.getElementById('agentsErrorMsg');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');

// --- roster (for the Start settings modal) ------------------------------

function loadRoster(){
  fetch('/api/agents/roster').then(r => r.json()).then(d => {
    aState.roster = d.roster || [];
    aState.roster.forEach(a => aState.selectedAgents.add(a.name));
  });
}
loadRoster();

// --- start-run settings modal --------------------------------------------

function agentSettingsModalHtml(){
  const picker = aState.roster.map(a => `
    <label class="checkbox-row">
      <input type="checkbox" data-agent-name="${escapeHtml(a.name)}" ${aState.selectedAgents.has(a.name) ? 'checked' : ''} />
      <span>${escapeHtml(a.name)}</span>
      <span class="sub">age ${a.age}</span>
    </label>
  `).join('') || '<div class="modal-empty">No agents available -- generate a history first.</div>';

  return `
    <div class="modal-header">
      <button class="modal-close" data-close>×</button>
      <h3>Start Agent Run</h3>
    </div>
    <div class="modal-field">
      <div class="field-row">
        <div class="field"><label>Ticks</label><input type="number" id="ticksInput" value="8" min="1" /></div>
        <div class="field"><label>Tick pause (s)</label><input type="number" id="tickSleepInput" value="0" min="0" step="0.5" /></div>
      </div>
      <div class="field">
        <label>Chat model (blank = server default)</label>
        <input type="text" id="modelInput" list="modelOptions" placeholder="auto" />
        <datalist id="modelOptions"></datalist>
      </div>
      <div class="field">
        <label>Context tokens (blank = server default)</label>
        <input type="number" id="contextInput" placeholder="auto" min="256" />
      </div>
    </div>
    <div class="modal-section-label">Agents</div>
    <div class="modal-body-pad" id="agentPicker">${picker}</div>
    <div class="modal-actions">
      <button class="primary" data-action="submit-start">▶ Start</button>
    </div>
  `;
}

function openAgentSettingsModal(){
  openModal(agentSettingsModalHtml());
  modalBodyEl.querySelector('[data-close]').addEventListener('click', closeModal);
  modalBodyEl.querySelectorAll('[data-agent-name]').forEach(el => {
    el.addEventListener('change', (e) => {
      if (e.target.checked) aState.selectedAgents.add(el.dataset.agentName);
      else aState.selectedAgents.delete(el.dataset.agentName);
    });
  });
  fetch('/api/agents/models').then(r => r.json()).then(d => {
    const list = modalBodyEl.querySelector('#modelOptions');
    if (!list) return;
    (d.models || []).forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      list.appendChild(opt);
    });
  });
  modalBodyEl.querySelector('[data-action="submit-start"]').addEventListener('click', startAgentRun);
}

startBtn.addEventListener('click', openAgentSettingsModal);

function startAgentRun(){
  const payload = {
    ticks: parseInt(document.getElementById('ticksInput').value, 10) || 8,
    tick_sleep: parseFloat(document.getElementById('tickSleepInput').value) || 0,
    chat_model: document.getElementById('modelInput').value.trim() || null,
    context_tokens: parseInt(document.getElementById('contextInput').value, 10) || null,
    agent_names: Array.from(aState.selectedAgents),
  };
  fetch('/api/agents/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => r.json()).then(d => {
    if (!d.ok) { errorMsg.textContent = d.error || 'could not start run'; return; }
    closeModal();
    pollAgentsState();
  });
}

stopBtn.addEventListener('click', () => {
  fetch('/api/agents/stop', { method: 'POST' });
});

// --- agent markers on the shared map --------------------------------------

function agentInitial(name){
  return (name.trim()[0] || '?').toUpperCase();
}

// Agents sharing a place get spread in a small ring around its marker so
// they don't sit exactly on top of one another (or the place marker).
function offsetsFor(count){
  if (count <= 1) return [{ dx: 0, dy: 0 }];
  const radius = 12;
  return Array.from({ length: count }, (_, i) => {
    const angle = (i / count) * Math.PI * 2;
    return { dx: Math.round(Math.cos(angle) * radius), dy: Math.round(Math.sin(angle) * radius) };
  });
}

function buildAgentMarkers(cityData, agents){
  const markerByPlaceId = new Map((cityData.map.graphic.markers || []).map(m => [m.place_id, m]));
  const placeIdByName = new Map(cityData.places.map(p => [p.name, p.id]));

  const byPlace = new Map();
  agents.forEach(a => {
    const placeId = placeIdByName.get(a.location);
    const marker = placeId ? markerByPlaceId.get(placeId) : null;
    if (!marker) return; // hardcoded noir roster locations don't resolve to a real place
    if (!byPlace.has(marker.place_id)) byPlace.set(marker.place_id, []);
    byPlace.get(marker.place_id).push({ agent: a, marker });
  });

  const extraMarkers = [];
  byPlace.forEach(entries => {
    const offsets = offsetsFor(entries.length);
    entries.forEach(({ agent, marker }, i) => {
      extraMarkers.push({
        row: marker.row, col: marker.col,
        dx: offsets[i].dx, dy: offsets[i].dy,
        color: agent.color, label: agentInitial(agent.name),
        onClick: () => openAgentModal(agent.name),
      });
    });
  });
  return extraMarkers;
}

function agentsSignature(agents){
  return agents.map(a => a.name + '@' + a.location).sort().join('|');
}

// --- agent detail modal (flat chronological log + media) -------------------

function eventText(ev){
  switch (ev.kind) {
    case 'plan': return `made a plan (${(ev.items || []).length} steps)`;
    case 'decompose': return `considering: ${ev.broad_step}`;
    case 'observe': return `notices: ${ev.text}`;
    case 'react': return `reacts: ${ev.text}`;
    case 'continue': return `sticks with the plan`;
    case 'memory': return `remembers (${ev.memory_kind}, importance ${Math.round(ev.importance)}/10): ${ev.text}`;
    case 'focal': return `wonders: ${ev.text}`;
    case 'insight': return `realizes: ${ev.text}`;
    case 'action': return `[T${ev.tick}] (${ev.location}) ${ev.text}`;
    case 'dialogue': return `→ ${ev.listener}: "${ev.text}"`;
    case 'reflect_pause': return `pauses to reflect.`;
    default: return ev.text || JSON.stringify(ev);
  }
}

function makeEventRow(ev){
  const meta = KIND_META[ev.kind] || { label: ev.kind.toUpperCase(), color: '#888' };
  const row = document.createElement('div');
  row.className = `event kind-${ev.kind}`;
  row.innerHTML = `
    <span class="badge" style="background:${meta.color}22; color:${meta.color}; border:1px solid ${meta.color}55">${meta.label}</span>
    <span class="content">${escapeHtml(eventText(ev))}</span>
  `;
  return row;
}

// Agents seeded from a generated history are literally that history's
// characters (see agents/simulation.py's roster_from_history) -- reuse
// the character's own id so a portrait attached here is the same one
// shown on their resident card. Falls back to a name-derived key for the
// hardcoded noir cast (no history, no character record to match).
function agentEntityId(agent){
  const character = hState.data && hState.data.characters
    ? hState.data.characters.find(c => c.name === agent.name) : null;
  return character ? character.id : `agent_${agent.name.replace(/\s+/g, '_')}`;
}

function openAgentModal(name){
  const agent = aState.agents.find(a => a.name === name);
  if (!agent) return;
  const entityId = agentEntityId(agent);

  openModal(`
    <div class="modal-header" style="border-left-color:${agent.color}">
      <button class="modal-close" data-close>×</button>
      <h3>${escapeHtml(agent.name)}</h3>
      <div class="modal-sub">age ${escapeHtml(String(agent.age))} · ${escapeHtml(agent.location || '')}</div>
    </div>
    ${agent.traits ? `<div class="modal-desc">${escapeHtml(agent.traits)}</div>` : ''}
    <div class="modal-body-pad">${entityMediaHtml(entityId, 'agent', `Describe a portrait of ${agent.name}…`)}</div>
    <div class="modal-section-label">Log</div>
    <div class="agent-log" id="agentModalLog"></div>
  `, { wide: true });
  modalBodyEl.querySelector('[data-close]').addEventListener('click', closeModal);

  fetch('/api/agents/events?since=0').then(r => r.json()).then(d => {
    const logEl = document.getElementById('agentModalLog');
    if (!logEl) return; // modal closed before this resolved
    const rows = (d.events || []).filter(ev => ev.agent === name);
    if (!rows.length) {
      logEl.innerHTML = '<div class="modal-empty">Nothing logged yet.</div>';
      return;
    }
    rows.forEach(ev => logEl.appendChild(makeEventRow(ev)));
  });
}

// --- treatment plate (Map tab, below the map) -------------------------------

function renderTreatment(text){
  aState.treatment = text;
  const plate = document.getElementById('treatmentPlate');
  if (!plate) return;
  if (!text) { plate.style.display = 'none'; return; }
  plate.style.display = '';
  document.getElementById('treatmentText').textContent = text;
}

// --- Logs tab: combined activity across every agent in the run -------------

let agentLogSince = 0;

function resetAgentLog(){
  agentLogSince = 0;
  const el = document.getElementById('agentLogLines');
  if (el) el.innerHTML = '';
}

function pollAgentLog(){
  fetch('/api/agents/events?since=' + agentLogSince).then(r => r.json()).then(d => {
    const el = document.getElementById('agentLogLines');
    if (el && d.events && d.events.length) {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 20;
      d.events.forEach(ev => {
        if (ev.kind === 'treatment') return; // shown in its own plate, not the log
        const row = makeEventRow(ev);
        if (ev.agent) {
          const color = (aState.agents.find(a => a.name === ev.agent) || {}).color || '#9ca3af';
          const prefix = document.createElement('span');
          prefix.style.cssText = `color:${color};font-weight:700;margin-right:6px;flex:none;`;
          prefix.textContent = ev.agent + ':';
          row.prepend(prefix);
        }
        el.appendChild(row);
      });
      if (atBottom) el.scrollTop = el.scrollHeight;
    }
    agentLogSince = d.next;
  }).catch(() => {});
}

// --- status polling ---------------------------------------------------------

function pollAgentsState(){
  fetch('/api/agents/state').then(r => r.json()).then(d => {
    aState.agents = d.agents || [];

    const phase = (d.status && d.status.phase) || 'idle';
    statusPill.className = 'status-pill ' + phase;
    statusText.textContent = phase;
    errorMsg.textContent = (d.status && d.status.error) || '';
    startBtn.disabled = phase === 'running';
    stopBtn.style.display = phase === 'running' ? '' : 'none';

    const isNewRun = d.started_at && d.started_at !== aState.lastStartedAt;
    if (isNewRun) {
      aState.lastStartedAt = d.started_at;
      renderTreatment(null);
      resetAgentLog();
    }

    // Redraw the shared map's agent-marker layer only when the roster or
    // anyone's location actually changed -- a full map redraw every poll
    // tick regardless would be wasted work (and a visible flicker).
    const sig = agentsSignature(aState.agents);
    if (sig !== aState.lastAgentsSignature) {
      aState.lastAgentsSignature = sig;
      if (typeof redrawCityMap === 'function') redrawCityMap();
    }

    if (phase !== 'idle') pollAgentLog();

    if (phase === 'done' && aState.lastPhase !== 'done') {
      fetch('/api/agents/events?since=0').then(r => r.json()).then(ed => {
        const treatmentEv = (ed.events || []).find(ev => ev.kind === 'treatment');
        if (treatmentEv) renderTreatment(treatmentEv.text);
      });
    }
    aState.lastPhase = phase;
  }).catch(() => {});
}

setInterval(pollAgentsState, 1200);
pollAgentsState();
