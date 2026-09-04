"use strict";

// ======================================================================
// Agents tab
// ======================================================================

const KIND_META = {
  plan:          { label: 'PLAN',      color: '#60a5fa', defaultOn: true },
  decompose:     { label: 'DECOMP',    color: '#3b82f6', defaultOn: true },
  observe:       { label: 'OBSERVES',  color: '#22d3ee', defaultOn: true },
  react:         { label: 'REACTS',    color: '#e879f9', defaultOn: true },
  continue:      { label: 'CONTINUES', color: '#6b7280', defaultOn: true },
  memory:        { label: 'MEMORY',    color: '#9ca3af', defaultOn: false },
  focal:         { label: 'FOCAL',     color: '#fbbf24', defaultOn: true },
  insight:       { label: 'INSIGHT',   color: '#f59e0b', defaultOn: true },
  action:        { label: 'ACTION',    color: '#e5e7eb', defaultOn: true },
  dialogue:      { label: 'DIALOGUE',  color: '#4ade80', defaultOn: true },
  reflect_pause: { label: 'REFLECT',   color: '#a78bfa', defaultOn: true },
  treatment:     { label: 'TREATMENT', color: '#fca5a5', defaultOn: true },
};

const state = {
  agents: [],              // current run's agents (name/color/etc)
  roster: [],               // every agent available to pick from
  selectedAgents: new Set(),
  agentFilter: new Set(),   // agent names whose whole column is hidden
  kindFilter: new Set(),    // event kinds hidden within a column
  search: "",
  perAgent: new Map(),      // name -> {outlineEl, planBlock, stepBlock, tickItem, stepCount}
  interactionsList: null,   // the Interactions column's conversation-list container
  lastConvKey: null,        // (pair + tick) signature of the conversation block in progress
  lastConvBlock: null,
  eventSource: null,
  lastStartedAt: null,      // detects a new/changed run (see pollState)
};

for (const kind in KIND_META) {
  if (!KIND_META[kind].defaultOn) state.kindFilter.add(kind);
}

const mainEl = document.getElementById('agentsMain');
const agentPickerEl = document.getElementById('agentPicker');
const agentLegendEl = document.getElementById('agentLegend');
const kindListEl = document.getElementById('kindList');
const searchBox = document.getElementById('searchBox');
const statusPill = document.getElementById('statusPill');
const statusText = document.getElementById('statusText');
const errorMsg = document.getElementById('errorMsg');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');

function agentColorByName(name){
  const a = state.agents.find(x => x.name === name);
  return a ? a.color : '#9ca3af';
}

// --- setup: roster + models -----------------------------------------

function loadRoster(){
  fetch('/api/agents/roster').then(r => r.json()).then(d => {
    state.roster = d.roster || [];
    state.roster.forEach(a => state.selectedAgents.add(a.name));
    renderAgentPicker();
  });
}
loadRoster();

fetch('/api/agents/models').then(r => r.json()).then(d => {
  const list = document.getElementById('modelOptions');
  (d.models || []).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    list.appendChild(opt);
  });
});

function renderAgentPicker(){
  agentPickerEl.innerHTML = '';
  state.roster.forEach(a => {
    const row = document.createElement('label');
    row.className = 'checkbox-row';
    row.innerHTML = `
      <input type="checkbox" ${state.selectedAgents.has(a.name) ? 'checked' : ''} />
      <span>${escapeHtml(a.name)}</span>
      <span class="sub">age ${a.age}</span>
    `;
    row.querySelector('input').addEventListener('change', (e) => {
      if (e.target.checked) state.selectedAgents.add(a.name);
      else state.selectedAgents.delete(a.name);
    });
    agentPickerEl.appendChild(row);
  });
}

function renderLegendAndKinds(){
  agentLegendEl.innerHTML = '';
  state.agents.forEach(a => {
    const row = document.createElement('div');
    row.className = 'agent-row' + (state.agentFilter.has(a.name) ? ' off' : '');
    row.title = `${a.traits || ''}${a.location ? ' — ' + a.location : ''}`;
    row.innerHTML = `
      <span class="swatch" style="background:${a.color}"></span>
      <span class="name" style="color:${a.color}">${escapeHtml(a.name)}</span>
    `;
    row.addEventListener('click', () => {
      if (state.agentFilter.has(a.name)) state.agentFilter.delete(a.name);
      else state.agentFilter.add(a.name);
      applyFilters();
      renderLegendAndKinds();
    });
    agentLegendEl.appendChild(row);
  });

  kindListEl.innerHTML = '';
  Object.keys(KIND_META).forEach(kind => {
    const meta = KIND_META[kind];
    const row = document.createElement('div');
    row.className = 'kind-row' + (state.kindFilter.has(kind) ? ' off' : '');
    row.innerHTML = `<span class="swatch" style="background:${meta.color}"></span><span>${meta.label}</span>`;
    row.addEventListener('click', () => {
      if (state.kindFilter.has(kind)) state.kindFilter.delete(kind);
      else state.kindFilter.add(kind);
      applyFilters();
      renderLegendAndKinds();
    });
    kindListEl.appendChild(row);
  });
}

function applyFilters(){
  document.querySelectorAll('.event[data-kind]').forEach(row => {
    const hideKind = state.kindFilter.has(row.dataset.kind);
    const hideSearch = state.search && !row.dataset.hay.includes(state.search);
    row.style.display = (hideKind || hideSearch) ? 'none' : '';
  });
  document.querySelectorAll('.agent-column[data-agent]').forEach(col => {
    col.style.display = state.agentFilter.has(col.dataset.agent) ? 'none' : '';
  });
  document.querySelectorAll('.convo-line[data-hay]').forEach(row => {
    row.style.display = (state.search && !row.dataset.hay.includes(state.search)) ? 'none' : '';
  });
  const interCol = document.querySelector('.interactions-column');
  if (interCol) interCol.style.display = state.kindFilter.has('dialogue') ? 'none' : '';
}

searchBox.addEventListener('input', () => {
  state.search = searchBox.value.trim().toLowerCase();
  applyFilters();
});

// --- outline rendering -------------------------------------------------
//
// Instead of grouping by tick, each agent gets its own column structured
// like an outline: PLAN > broad step > that step's substeps-in-progress.
// Everything else an agent does at a given tick (observing, reacting,
// forming a memory, chatting) nests under that tick's action line, so a
// deviation from the plan (a REACT) shows as a branch right where it
// happened, and the next action -- still pulled from the same substep
// list, since react() never touches the plan cursor -- makes the "jump
// back" to the plan visually obvious as the very next line in the outline.

function eventText(ev){
  switch (ev.kind) {
    case 'observe': return `notices: ${ev.text}`;
    case 'react': return `reacts: ${ev.text}`;
    case 'continue': return `sticks with the plan`;
    case 'memory': return `remembers (${ev.memory_kind}, importance ${Math.round(ev.importance)}/10): ${ev.text}`;
    case 'focal': return `wonders: ${ev.text}`;
    case 'insight': return `realizes: ${ev.text}`;
    case 'dialogue': return `→ ${ev.listener}: "${ev.text}"`;
    case 'reflect_pause': return `pauses to reflect.`;
    default: return ev.text || JSON.stringify(ev);
  }
}

function makeEventRow(ev, contentHtml){
  const meta = KIND_META[ev.kind] || { label: ev.kind.toUpperCase(), color: '#888' };
  const row = document.createElement('div');
  row.className = `event kind-${ev.kind}`;
  row.dataset.kind = ev.kind;
  row.dataset.hay = JSON.stringify(ev).toLowerCase();
  row.innerHTML = `
    <span class="badge" style="background:${meta.color}22; color:${meta.color}; border:1px solid ${meta.color}55">${meta.label}</span>
    <span class="content">${contentHtml}</span>
  `;
  if (state.kindFilter.has(ev.kind) || (state.search && !row.dataset.hay.includes(state.search))) {
    row.style.display = 'none';
  }
  return row;
}

function rebuildColumns(agents){
  mainEl.innerHTML = '';
  state.perAgent = new Map();
  state.lastConvKey = null;
  state.lastConvBlock = null;

  const interCol = document.createElement('div');
  interCol.className = 'agent-column interactions-column';
  if (state.kindFilter.has('dialogue')) interCol.style.display = 'none';
  interCol.innerHTML = `
    <div class="agent-col-header" style="border-color:${KIND_META.dialogue.color}88">
      <span class="swatch" style="background:${KIND_META.dialogue.color}"></span>
      <span class="name" style="color:${KIND_META.dialogue.color}">Interactions</span>
      <span class="sub">who's talking to whom</span>
    </div>
    <div class="convo-list"></div>
  `;
  mainEl.appendChild(interCol);
  state.interactionsList = interCol.querySelector('.convo-list');

  agents.forEach(a => {
    const col = document.createElement('div');
    col.className = 'agent-column';
    col.dataset.agent = a.name;
    if (state.agentFilter.has(a.name)) col.style.display = 'none';
    col.innerHTML = `
      <div class="agent-col-header" style="border-color:${a.color}88">
        <span class="swatch" style="background:${a.color}"></span>
        <span class="name" style="color:${a.color}">${escapeHtml(a.name)}</span>
        <span class="sub">${escapeHtml(a.location || '')}</span>
      </div>
      <div class="outline"></div>
    `;
    mainEl.appendChild(col);
    state.perAgent.set(a.name, {
      outlineEl: col.querySelector('.outline'),
      planBlock: null, stepBlock: null, tickItem: null, stepCount: 0,
    });
  });
}

function renderTreatment(ev){
  const card = document.createElement('div');
  card.className = 'treatment-card';
  card.innerHTML = `<div class="head">Treatment</div><pre>${escapeHtml(ev.text)}</pre>`;
  mainEl.appendChild(card);
}

function renderEvent(ev){
  if (ev.kind === 'treatment') return renderTreatment(ev);

  const as = state.perAgent.get(ev.agent);
  if (!as) return; // column not built yet -- rare startup race, safe to drop

  if (ev.kind === 'plan') {
    as.stepCount = 0;
    const block = document.createElement('details');
    block.open = true;
    block.className = 'plan-block';
    block.innerHTML = `<summary>Plan — tick ${ev.tick} · ${(ev.items || []).length} steps</summary>`;
    as.outlineEl.appendChild(block);
    as.planBlock = block;
    as.stepBlock = null;
    as.tickItem = null;
    return;
  }

  if (ev.kind === 'decompose') {
    as.stepCount += 1;
    const block = document.createElement('details');
    block.open = true;
    block.className = 'step-block';
    block.innerHTML = `<summary>${as.stepCount}. ${escapeHtml(ev.broad_step)}</summary>`;
    (as.planBlock || as.outlineEl).appendChild(block);
    as.stepBlock = block;
    as.tickItem = null;
    return;
  }

  if (ev.kind === 'action') {
    const item = document.createElement('div');
    item.className = 'tick-item';
    const row = makeEventRow(ev, `<span class="tick-tag">T${ev.tick}</span>(${escapeHtml(ev.location)}) ${escapeHtml(ev.text)}`);
    item.appendChild(row);
    const nested = document.createElement('div');
    nested.className = 'nested';
    item.appendChild(nested);
    (as.stepBlock || as.outlineEl).appendChild(item);
    as.tickItem = item;
    return;
  }

  // everything else nests under the most recent action's tick-item
  const target = as.tickItem ? as.tickItem.querySelector('.nested') : as.outlineEl;
  const row = makeEventRow(ev, escapeHtml(eventText(ev)));
  target.appendChild(row);
  if (ev.kind === 'react' && as.tickItem) as.tickItem.classList.add('has-react');
  if (ev.kind === 'dialogue') renderInteraction(ev);
}

function conversationKey(ev){
  // unordered pair + tick, so both speakers' turns in one exchange group
  // into the same block regardless of who's "agent" on a given line
  return [ev.agent, ev.listener].sort().join('|') + '@' + ev.tick;
}

function renderInteraction(ev){
  if (!state.interactionsList) return;
  const key = conversationKey(ev);
  if (state.lastConvKey !== key) {
    const aColor = agentColorByName(ev.agent);
    const bColor = agentColorByName(ev.listener);
    const block = document.createElement('div');
    block.className = 'convo-block';
    block.innerHTML = `
      <div class="convo-head">T${ev.tick} · <span style="color:${aColor}">${escapeHtml(ev.agent)}</span> ↔ <span style="color:${bColor}">${escapeHtml(ev.listener)}</span></div>
      <div class="convo-lines"></div>
    `;
    state.interactionsList.appendChild(block);
    state.lastConvKey = key;
    state.lastConvBlock = block;
  }
  const line = document.createElement('div');
  line.className = 'convo-line';
  line.dataset.hay = JSON.stringify(ev).toLowerCase();
  line.innerHTML = `<span class="who" style="color:${agentColorByName(ev.agent)}">${escapeHtml(ev.agent)}:</span> <span class="line-text">"${escapeHtml(ev.text)}"</span>`;
  if (state.search && !line.dataset.hay.includes(state.search)) line.style.display = 'none';
  state.lastConvBlock.querySelector('.convo-lines').appendChild(line);
}

// --- streaming ----------------------------------------------------

function connectStream(){
  if (state.eventSource) state.eventSource.close();
  const es = new EventSource('/api/agents/stream?since=0');
  es.onmessage = (e) => renderEvent(JSON.parse(e.data));
  state.eventSource = es;
}

// --- status polling -------------------------------------------------

function pollState(){
  fetch('/api/agents/state').then(r => r.json()).then(d => {
    state.agents = d.agents || [];

    if (d.started_at && d.started_at !== state.lastStartedAt) {
      // a new (or newly-caught-up) run -- rebuild columns and replay
      // its events from the start
      state.lastStartedAt = d.started_at;
      rebuildColumns(state.agents);
      connectStream();
    }

    renderLegendAndKinds();

    const phase = (d.status && d.status.phase) || 'idle';
    statusPill.className = 'status-pill ' + phase;
    statusText.textContent = phase;
    errorMsg.textContent = (d.status && d.status.error) || '';

    startBtn.disabled = phase === 'running';
    stopBtn.style.display = phase === 'running' ? '' : 'none';
  }).catch(() => {});
}

setInterval(pollState, 1200);
pollState();

// --- controls -------------------------------------------------------

startBtn.addEventListener('click', () => {
  const payload = {
    ticks: parseInt(document.getElementById('ticksInput').value, 10) || 8,
    tick_sleep: parseFloat(document.getElementById('tickSleepInput').value) || 0,
    chat_model: document.getElementById('modelInput').value.trim() || null,
    context_tokens: parseInt(document.getElementById('contextInput').value, 10) || null,
    agent_names: Array.from(state.selectedAgents),
  };
  fetch('/api/agents/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => r.json()).then(d => {
    if (!d.ok) { errorMsg.textContent = d.error || 'could not start run'; return; }
    pollState();
  });
});

stopBtn.addEventListener('click', () => {
  fetch('/api/agents/stop', { method: 'POST' });
});
