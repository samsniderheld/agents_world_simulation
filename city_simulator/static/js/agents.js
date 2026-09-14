"use strict";

// ======================================================================
// Agents -- no tab of their own anymore: agents render as a second
// marker layer on the shared city map (see history.js's redrawCityMap(),
// citymap.js's buildCityMap()), and their combined activity log lives on
// the Logs tab. This file owns: the roster/settings modal, feeding agent
// markers into the shared map, the agent detail modal (with the same
// image/video generation controls a place gets, plus a manual "Generate
// Treatment" section), and the Logs tab's Agent Activity panel.
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
  move:          { label: 'MOVE',      color: '#2dd4bf' },
  reflect_pause: { label: 'REFLECT',   color: '#a78bfa' },
};

const aState = {
  agents: [],              // current run's agents (name/color/age/traits/location)
  roster: [],               // every agent available to pick from
  selectedAgents: new Set(),
  lastStartedAt: null,      // detects a new/changed run
  lastPhase: null,
  lastAgentsSignature: null, // name@location per agent -- redraw the map only when this changes
  agentRecords: {},          // character id -> their persisted agents/<id>/agent.json, once fetched
};

// Deterministic per-name color, used everywhere an agent needs one (map
// markers, activity-log prefixes, the modal's header bar) -- not the live
// run's server-assigned color (display.agent_hex_colors(), a fresh
// assignment every run), so an agent who only has *persisted* history and
// isn't part of the current run still gets a real, stable color instead
// of needing a live roster entry to draw from.
function agentColorFor(name){
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return `hsl(${Math.abs(hash) % 360}, 65%, 60%)`;
}

const statusPill = document.getElementById('agentsStatusPill');
const statusText = document.getElementById('agentsStatusText');
const errorMsg = document.getElementById('agentsErrorMsg');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');

// --- roster (for the Start settings modal) ------------------------------

// Returns a promise so callers can wait for fresh data -- this used to
// only be called once at page load, which meant generating a history
// *after* the page was already open left aState.roster (and so the Start
// Agents modal's picker) permanently empty, since nothing ever re-fetched
// it once real characters existed. openAgentSettingsModal() below now
// calls this itself right before rendering, every time it opens.
function loadRoster(){
  return fetch('/api/agents/roster').then(r => r.json()).then(d => {
    aState.roster = d.roster || [];
    // Drop selections for names that no longer exist (e.g. history was
    // regenerated with a different cast); if that empties the selection
    // entirely -- including the very first load -- default to everyone.
    const validNames = new Set(aState.roster.map(a => a.name));
    aState.selectedAgents = new Set([...aState.selectedAgents].filter(n => validNames.has(n)));
    if (!aState.selectedAgents.size) aState.roster.forEach(a => aState.selectedAgents.add(a.name));
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
        <label>Provider</label>
        <select id="providerInput">
          <option value="ollama">Ollama (local)</option>
          <option value="claude">Claude (API)</option>
        </select>
        <span class="field-hint">Claude still uses your local Ollama for memory embeddings.</span>
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
    <div class="modal-body-pad">${picker}</div>
    <div class="modal-actions">
      <button class="primary" data-action="submit-start">▶ Start</button>
    </div>
  `;
}

// Refreshes the Chat model <datalist> for whichever provider is currently
// selected -- called on modal open and again whenever the Provider select
// changes, since Ollama/Claude have entirely different model lists.
function refreshModelOptions(provider){
  fetch(`/api/agents/models?provider=${encodeURIComponent(provider)}`).then(r => r.json()).then(d => {
    const list = modalBodyEl.querySelector('#modelOptions');
    if (!list) return;
    list.innerHTML = '';
    (d.models || []).forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      list.appendChild(opt);
    });
  });
}

function openAgentSettingsModal(){
  loadRoster().then(() => {
    openModal(agentSettingsModalHtml());
    modalBodyEl.querySelector('[data-close]').addEventListener('click', closeModal);
    modalBodyEl.querySelectorAll('[data-agent-name]').forEach(el => {
      el.addEventListener('change', (e) => {
        if (e.target.checked) aState.selectedAgents.add(el.dataset.agentName);
        else aState.selectedAgents.delete(el.dataset.agentName);
      });
    });
    const providerSelect = modalBodyEl.querySelector('#providerInput');
    refreshModelOptions(providerSelect.value);
    providerSelect.addEventListener('change', () => {
      document.getElementById('modelInput').value = '';
      refreshModelOptions(providerSelect.value);
    });
    modalBodyEl.querySelector('[data-action="submit-start"]').addEventListener('click', startAgentRun);
  });
}

startBtn.addEventListener('click', openAgentSettingsModal);

function startAgentRun(){
  const payload = {
    ticks: parseInt(document.getElementById('ticksInput').value, 10) || 8,
    provider: document.getElementById('providerInput').value,
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

// Who gets a marker: anyone in the *live* run roster (their current-run
// location), plus -- so a page reload or a city with no run yet this
// session still shows people -- anyone else who has at least one
// *persisted* run on record (agents/<id>/agent.json's "runs"), placed at
// their character's grounding location (world.py gives agents a fixed
// location for a whole run, so that's also their last-known one). Without
// this second group, agent markers only ever appeared after clicking
// Start Agents in the current browser session, even though the map is
// meant to reflect what's actually been persisted.
function agentsToShow(cityData, liveAgents){
  const liveByName = new Map(liveAgents.map(a => [a.name, a]));
  const shown = [];
  (cityData.characters || []).forEach(c => {
    const live = liveByName.get(c.name);
    if (live) {
      shown.push({ name: c.name, location: live.location });
      return;
    }
    const record = aState.agentRecords[c.id];
    if (record && record.runs && record.runs.length) {
      shown.push({ name: c.name, location: c.place_name || '' });
    }
  });
  return shown;
}

function buildAgentMarkers(cityData, liveAgents){
  const markerByPlaceId = new Map((cityData.map.graphic.markers || []).map(m => [m.place_id, m]));
  const placeIdByName = new Map(cityData.places.map(p => [p.name, p.id]));

  const byPlace = new Map();
  agentsToShow(cityData, liveAgents).forEach(a => {
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
        color: agentColorFor(agent.name), label: agentInitial(agent.name),
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
    case 'move': return `moved to ${ev.to_location} (from ${ev.from_location})`;
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

function planHtml(plan){
  const items = (plan.items || []).map(i => `<li>${escapeHtml(i)}</li>`).join('');
  const when = plan.run_started_at ? new Date(plan.run_started_at).toLocaleString() : 'unknown run';
  return `<div class="agent-plan"><div class="agent-plan-meta">Tick ${plan.tick} · run started ${escapeHtml(when)}</div><ol>${items}</ol></div>`;
}

// Basic bio for the modal header -- the live run roster if they're part
// of it, otherwise derived from their character record (the same fields
// agents/simulation.py's roster_from_history() would derive), so opening
// an agent's marker still works when nothing has run yet this session.
function agentBasicInfo(name){
  const live = aState.agents.find(a => a.name === name);
  const character = hState.data && hState.data.characters
    ? hState.data.characters.find(c => c.name === name) : null;
  if (live) return { name: live.name, age: live.age, traits: live.traits, location: live.location, bio: character ? character.bio : '' };
  if (!character) return null;
  let traits = (character.occupation || '').trim();
  if (character.quirk) traits = traits ? `${traits}; ${character.quirk}` : character.quirk;
  return { name: character.name, age: character.age, traits: traits || 'a longtime local', location: character.place_name || '', bio: character.bio || '' };
}

// Reads the agent's *persistent* record (citystate/store.py's
// agents/<id>/agent.json -- their plans and every run they've taken part
// in, across restarts) rather than /api/agents/events, which is only the
// current process's live in-memory recorder feed and resets to nothing
// on every new run. That mismatch was the bug: opening an agent's modal
// after a second run only ever showed that one run, as if the first had
// never happened -- this is what makes their log actually continuous.
function openAgentModal(name){
  const agent = agentBasicInfo(name);
  if (!agent) return;
  const entityId = agentEntityId(agent);
  const color = agentColorFor(agent.name);

  openModal(`
    <div class="modal-header" style="border-left-color:${color}">
      <button class="modal-close" data-close>×</button>
      <h3>${escapeHtml(agent.name)}</h3>
      <div class="modal-sub">age ${escapeHtml(String(agent.age))} · ${escapeHtml(agent.location || '')}</div>
    </div>
    ${agent.traits ? `<div class="modal-desc">${escapeHtml(agent.traits)}</div>` : ''}
    <div class="modal-body-pad">${entityMediaHtml(entityId, 'agent', agentMediaPrompt(agent))}</div>
    <div class="modal-body-pad" id="agentModalHistory"></div>
    <div class="modal-section-label">Plans</div>
    <div class="agent-plans" id="agentModalPlans"></div>
    <div class="modal-section-label">Log</div>
    <div class="agent-log" id="agentModalLog"></div>
    <div class="modal-section-label">Treatment</div>
    <div class="agent-treatments" id="agentModalTreatments"></div>
    <div class="modal-field" id="agentModalTreatmentControls"></div>
    <div class="modal-actions" id="agentModalTreatmentActions"></div>
  `, { wide: true });
  modalBodyEl.querySelector('[data-close]').addEventListener('click', closeModal);

  fetch(`/api/city/agents/${encodeURIComponent(entityId)}`).then(r => r.ok ? r.json() : null).then(data => {
    const historyEl = document.getElementById('agentModalHistory');
    const plansEl = document.getElementById('agentModalPlans');
    const logEl = document.getElementById('agentModalLog');
    const treatmentsEl = document.getElementById('agentModalTreatments');
    const treatmentControlsEl = document.getElementById('agentModalTreatmentControls');
    const treatmentActionsEl = document.getElementById('agentModalTreatmentActions');
    if (!historyEl || !plansEl || !logEl || !treatmentsEl || !treatmentControlsEl || !treatmentActionsEl) return; // modal closed before this resolved

    historyEl.innerHTML = lifeHistoryHtml(data && data.history);

    const plans = (data && data.plans) || [];
    plansEl.innerHTML = plans.length
      ? plans.map(planHtml).join('')
      : '<div class="modal-empty">No plans yet.</div>';

    const runs = (data && data.runs) || [];
    logEl.innerHTML = runs.length ? '' : '<div class="modal-empty">Nothing logged yet.</div>';
    runs.forEach(run => {
      const header = document.createElement('div');
      header.className = 'agent-run-header';
      header.textContent = `Run started ${run.started_at ? new Date(run.started_at).toLocaleString() : ''}`;
      logEl.appendChild(header);
      (run.events || []).forEach(ev => logEl.appendChild(makeEventRow(ev)));
    });

    renderAgentTreatments((data && data.treatments) || []);
    if (runs.length) {
      treatmentControlsEl.innerHTML = `
        <div class="field-row">
          <div class="field">
            <label>Provider</label>
            <select id="treatmentProviderInput">
              <option value="">Default</option>
              <option value="ollama">Ollama (local)</option>
              <option value="claude">Claude (API)</option>
            </select>
          </div>
          <div class="field">
            <label>Model (blank = provider default)</label>
            <input type="text" id="treatmentModelInput" list="treatmentModelOptions" placeholder="auto" />
            <datalist id="treatmentModelOptions"></datalist>
          </div>
        </div>
      `;
      treatmentActionsEl.innerHTML = '<button class="primary" data-action="generate-treatment">🎬 Generate Treatment</button><span class="media-status" id="agentTreatmentStatus"></span>';
      const providerSelect = document.getElementById('treatmentProviderInput');
      refreshTreatmentModelOptions(providerSelect.value);
      providerSelect.addEventListener('change', () => {
        document.getElementById('treatmentModelInput').value = '';
        refreshTreatmentModelOptions(providerSelect.value);
      });
      const genBtn = treatmentActionsEl.querySelector('[data-action="generate-treatment"]');
      if (genBtn) genBtn.addEventListener('click', () => generateAgentTreatment(entityId));
    } else {
      treatmentControlsEl.innerHTML = '';
      treatmentActionsEl.innerHTML = '<div class="modal-empty">No runs yet -- start agents first.</div>';
    }
  });
}

function refreshTreatmentModelOptions(provider){
  fetch(`/api/agents/models?provider=${encodeURIComponent(provider)}`).then(r => r.json()).then(d => {
    const list = document.getElementById('treatmentModelOptions');
    if (!list) return;
    list.innerHTML = '';
    (d.models || []).forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      list.appendChild(opt);
    });
  });
}

function renderAgentTreatments(treatments){
  const el = document.getElementById('agentModalTreatments');
  if (!el) return;
  el.innerHTML = treatments.length
    ? treatments.map(treatmentEntryHtml).join('')
    : '<div class="modal-empty">No treatments generated yet.</div>';
}

function treatmentEntryHtml(entry){
  const when = entry.created_at ? new Date(entry.created_at).toLocaleString() : '';
  return `<div class="agent-treatment"><div class="agent-treatment-meta">${escapeHtml(when)}</div><pre>${escapeHtml(entry.text)}</pre></div>`;
}

function generateAgentTreatment(entityId){
  const statusEl = document.getElementById('agentTreatmentStatus');
  const btn = modalBodyEl.querySelector('[data-action="generate-treatment"]');
  const provider = document.getElementById('treatmentProviderInput');
  const model = document.getElementById('treatmentModelInput');
  if (btn) btn.disabled = true;
  if (statusEl) statusEl.textContent = 'generating…';
  fetch('/api/agents/treatment', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      agent_id: entityId,
      provider: provider ? (provider.value || null) : null,
      model: model ? (model.value.trim() || null) : null,
    }),
  }).then(r => r.json()).then(d => {
    if (btn) btn.disabled = false;
    if (!d.treatment) {
      if (statusEl) statusEl.textContent = d.error || 'could not generate a treatment';
      return;
    }
    if (statusEl) statusEl.textContent = '';
    const el = document.getElementById('agentModalTreatments');
    if (!el) return; // modal closed before this resolved
    if (el.querySelector('.modal-empty')) el.innerHTML = '';
    el.insertAdjacentHTML('beforeend', treatmentEntryHtml(d.treatment));
  }).catch(() => {
    if (btn) btn.disabled = false;
    if (statusEl) statusEl.textContent = 'network error';
  });
}

// --- Agent Activity Log (Map tab, next to the map) --------------------------
//
// Two containers, not one, so "accumulate across runs" and "watch the
// current run live" don't fight each other: #agentLogHistory is rebuilt
// from every agent's *persisted* record (citystate/store.py's
// agents/<id>/agent.json -- survives restarts, every completed run) each
// time one becomes available; #agentLogLive is the current run's
// tick-by-tick feed from the ephemeral /api/agents/events recorder buffer,
// cleared when a new run starts and folded into the history side (then
// cleared again) the moment that run finishes -- so nothing is ever lost
// to "starts from scratch" on the next run, and you can still watch a run
// happen in real time.

let agentLogSince = 0;
let agentLogHistoryLoaded = false;

function agentLogRowHtml(ev, agentName){
  const row = makeEventRow(ev);
  if (agentName) {
    const color = agentColorFor(agentName);
    const prefix = document.createElement('span');
    prefix.style.cssText = `color:${color};font-weight:700;margin-right:6px;flex:none;`;
    prefix.textContent = agentName + ':';
    row.prepend(prefix);
  }
  return row;
}

function runHeaderEl(label){
  const header = document.createElement('div');
  header.className = 'agent-run-header';
  header.textContent = label;
  return header;
}

function refreshAgentLogHistory(){
  if (!hState.data || !hState.data.characters || !hState.data.characters.length) return;
  const el = document.getElementById('agentLogHistory');
  if (!el) return;
  agentLogHistoryLoaded = true;

  Promise.all(hState.data.characters.map(c =>
    fetch(`/api/city/agents/${encodeURIComponent(c.id)}`).then(r => r.ok ? r.json() : null)
      .then(rec => { aState.agentRecords[c.id] = rec; return rec; })
  )).then(records => {
    const byRun = new Map();  // started_at -> [{ev, agentName}], in original per-agent order
    records.forEach(rec => {
      if (!rec) return;
      (rec.runs || []).forEach(run => {
        const key = run.started_at || '';
        if (!byRun.has(key)) byRun.set(key, []);
        (run.events || []).forEach(ev => byRun.get(key).push({ ev, agentName: rec.name }));
      });
    });

    const runKeys = Array.from(byRun.keys()).sort();
    if (!runKeys.length) {
      el.innerHTML = '<div class="modal-empty">No completed runs yet.</div>';
    } else {
      el.innerHTML = '';
      runKeys.forEach(key => {
        el.appendChild(runHeaderEl(key ? `Run started ${new Date(key).toLocaleString()}` : 'Run'));
        // Stable sort: preserves each agent's own recorded order for events
        // at the same tick, just interleaves different agents by tick.
        byRun.get(key)
          .sort((a, b) => (a.ev.tick || 0) - (b.ev.tick || 0))
          .forEach(({ ev, agentName }) => el.appendChild(agentLogRowHtml(ev, agentName)));
      });
    }

    // Now that we know who actually has persisted runs, the map's agent
    // markers can include them too (see agentsToShow()) -- not just
    // whoever's in the current live roster.
    if (typeof redrawCityMap === 'function') redrawCityMap();
  }).catch(() => {});
}

function resetAgentLog(startedAt){
  agentLogSince = 0;
  const el = document.getElementById('agentLogLive');
  if (!el) return;
  el.innerHTML = '';
  if (startedAt) {
    el.appendChild(runHeaderEl(`Run started ${new Date(startedAt).toLocaleString()} (in progress)`));
  }
}

function pollAgentLog(){
  fetch('/api/agents/events?since=' + agentLogSince).then(r => r.json()).then(d => {
    const el = document.getElementById('agentLogLive');
    if (el && d.events && d.events.length) {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 20;
      d.events.forEach(ev => el.appendChild(agentLogRowHtml(ev, ev.agent)));
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

    if (!agentLogHistoryLoaded) refreshAgentLogHistory();

    const isNewRun = d.started_at && d.started_at !== aState.lastStartedAt;
    if (isNewRun) {
      aState.lastStartedAt = d.started_at;
      resetAgentLog(d.started_at);
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
      refreshAgentLogHistory();  // fold the just-finished run into the persisted side
      resetAgentLog();           // ...and clear the now-redundant live side
    }
    aState.lastPhase = phase;
  }).catch(() => {});
}

setInterval(pollAgentsState, 1200);
pollAgentsState();
