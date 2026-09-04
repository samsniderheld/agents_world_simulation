"use strict";

// ======================================================================
// History tab
// ======================================================================

const hState = { lastPhase: null, data: null, search: "", placeType: "", status: "", logSince: 0 };

const historyStatusPill = document.getElementById('historyStatusPill');
const historyStatusText = document.getElementById('historyStatusText');
const historyErrorMsg = document.getElementById('historyErrorMsg');
const generateBtn = document.getElementById('generateBtn');

function parseIntOrNull(v){
  const n = parseInt(v, 10);
  return Number.isFinite(n) ? n : null;
}

function buildIndexes(data){
  const figuresById = new Map(data.figures.map(f => [f.id, f]));
  const placesByEra = new Map(data.eras.map(e => [e.id, []]));
  const figuresByEra = new Map(data.eras.map(e => [e.id, []]));

  data.figures.forEach(f => { if (figuresByEra.has(f.era_id)) figuresByEra.get(f.era_id).push(f); });
  data.places.forEach(p => {
    const founder = figuresById.get(p.founding_figure_id);
    const eraId = founder ? founder.era_id : null;
    if (placesByEra.has(eraId)) placesByEra.get(eraId).push(p);
  });

  return { placesByEra, figuresByEra };
}

function renderHeader(data){
  document.getElementById('citySubtitle').textContent =
    `${data.eras[0].start_year}–${data.eras[data.eras.length - 1].end_year} · generated ${new Date(data.generated_at).toLocaleString()}`;
  document.getElementById('cityStats').textContent =
    `${data.eras.length} eras · ${data.figures.length} figures · ${data.places.length} places · ${data.events.length} events`;
}

function renderMap(data){
  const map = data.map;
  if (!map || typeof map !== 'object') {
    document.getElementById('mapText').textContent = map || '';
    return;
  }

  const palette = map.palette || {};
  const colorFor = (eraId) => {
    if (eraId === null || eraId === undefined) return palette.water || '#3b5f7a';
    return palette[eraId] || palette.default || '#d4d4d4';
  };

  // Color each character by which neighborhood (era row-band) it's in,
  // or water -- this is what carves each landmass into its actual
  // neighborhoods instead of leaving it one flat color. Grouped into
  // runs per row so the HTML stays compact rather than one span per
  // character.
  const coloredRows = (map.rows || []).map((line, r) => {
    const hoods = (map.cell_neighborhoods && map.cell_neighborhoods[r]) || [];
    let html = '', runColor = null, runText = '';
    const flush = () => {
      if (runText) html += `<span style="color:${runColor}">${escapeHtml(runText)}</span>`;
      runText = '';
    };
    for (let c = 0; c < line.length; c++) {
      const color = colorFor(hoods[c]);
      if (color !== runColor) { flush(); runColor = color; }
      runText += line[c];
    }
    flush();
    return (map.row_prefix || '') + html;
  });

  const header = (map.header_lines || []).map(escapeHtml).join('\n');
  const border = escapeHtml(map.border_line || '');
  document.getElementById('mapText').innerHTML =
    `${header}\n${coloredRows.join('\n')}\n${border}`;
  document.getElementById('mapCaption').textContent = map.caption || '';

  const keyEl = document.getElementById('neighborhoodKey');
  keyEl.innerHTML = (map.neighborhoods || []).map(n =>
    `<span class="entry"><span class="swatch" style="background:${n.color}"></span>${escapeHtml(n.name)}</span>`
  ).join('');
}

function populateTypeFilter(data){
  const select = document.getElementById('typeFilter');
  select.innerHTML = '<option value="">All place types</option>';
  const types = Array.from(new Set(data.places.map(p => p.place_type))).sort();
  types.forEach(t => {
    const opt = document.createElement('option');
    opt.value = t; opt.textContent = t;
    select.appendChild(opt);
  });
}

function placeCardHtml(place){
  const statusClass = place.status !== 'active' ? 'status-destroyed' : '';
  const statusText = place.status === 'active'
    ? `founded ${place.founded_year}`
    : `founded ${place.founded_year}, ${place.status}${place.closed_year ? ' ' + place.closed_year : ''}`;
  const historyHtml = place.history.map(h =>
    `<div class="entry"><span class="year">${h.year}</span>${escapeHtml(h.gospel_text)}</div>`
  ).join('');
  const hay = [place.name, place.place_type, place.domain, ...place.history.map(h => h.gospel_text)]
    .join(' ').toLowerCase();

  return `
    <div class="place-card" id="place-${escapeHtml(place.id)}" data-type="${escapeHtml(place.place_type)}" data-status="${escapeHtml(place.status)}" data-hay="${escapeHtml(hay)}">
      <div class="name">${escapeHtml(place.name)}</div>
      <div class="meta">${escapeHtml(place.place_type)} · domain: ${escapeHtml(place.domain)} · <span class="${statusClass}">${statusText}</span></div>
      <details>
        <summary>${place.history.length} recorded event${place.history.length === 1 ? '' : 's'}</summary>
        <div class="history">${historyHtml}</div>
      </details>
    </div>
  `;
}

function figureRowHtml(figure){
  const lifespan = figure.death_year ? `${figure.birth_year}–${figure.death_year}` : `b. ${figure.birth_year}`;
  return `<div class="figure-row"><b>${escapeHtml(figure.name)}</b> <span class="role">— ${escapeHtml(figure.role)}, domain: ${escapeHtml(figure.domain)} (${lifespan})</span></div>`;
}

function renderEras(data, indexes){
  const container = document.getElementById('eraSections');
  container.innerHTML = '';
  data.eras.forEach(era => {
    const places = indexes.placesByEra.get(era.id) || [];
    const figures = indexes.figuresByEra.get(era.id) || [];

    const section = document.createElement('section');
    section.className = 'era-section';
    section.dataset.eraId = era.id;
    section.innerHTML = `
      <div class="era-header">
        <h2>${escapeHtml(era.name)}</h2>
        <div class="years">${era.start_year}–${era.end_year}</div>
        <div class="desc">${escapeHtml(era.description)}</div>
      </div>
      <div class="place-grid">${places.map(placeCardHtml).join('') || '<p style="color:var(--text-faint);font-style:italic;">No places founded this era.</p>'}</div>
      ${figures.length ? `
        <details class="figures-toggle">
          <summary>${figures.length} notable figure${figures.length === 1 ? '' : 's'} from this era</summary>
          <div class="figures-list">${figures.map(figureRowHtml).join('')}</div>
        </details>
      ` : ''}
    `;
    container.appendChild(section);
  });
}

function residentCardHtml(person){
  const linkHtml = person.place_id
    ? `<a class="link" href="#place-${escapeHtml(person.place_id)}">→ ${escapeHtml(person.place_name)}</a>`
    : '';
  return `
    <div class="resident-card">
      <div class="name">${escapeHtml(person.name)}</div>
      <div class="role">${escapeHtml(String(person.age))} · ${escapeHtml(person.occupation)}</div>
      ${person.quirk ? `<div class="quirk">${escapeHtml(person.quirk)}</div>` : ''}
      <div class="bio">${escapeHtml(person.bio)}</div>
      ${linkHtml}
    </div>
  `;
}

function renderResidents(data){
  const people = data.characters || [];
  document.getElementById('residentsSection').style.display = people.length ? '' : 'none';
  document.getElementById('residentGrid').innerHTML = people.map(residentCardHtml).join('');
}

function applyHistoryFilters(){
  let visible = 0;
  document.querySelectorAll('.place-card').forEach(card => {
    const matchesType = !hState.placeType || card.dataset.type === hState.placeType;
    const matchesStatus = !hState.status || card.dataset.status === hState.status;
    const matchesSearch = !hState.search || card.dataset.hay.includes(hState.search);
    const show = matchesType && matchesStatus && matchesSearch;
    card.classList.toggle('hidden', !show);
    if (show) visible++;
  });

  document.querySelectorAll('.era-section').forEach(section => {
    const anyVisible = section.querySelectorAll('.place-card:not(.hidden)').length > 0;
    const hasCards = section.querySelectorAll('.place-card').length > 0;
    section.classList.toggle('hidden', hasCards && !anyVisible);
  });

  document.getElementById('visibleCount').textContent = `${visible} of ${document.querySelectorAll('.place-card').length} places shown`;
  document.getElementById('emptyNote').style.display = visible === 0 ? 'block' : 'none';
}

document.getElementById('historySearchBox').addEventListener('input', (e) => {
  hState.search = e.target.value.trim().toLowerCase();
  applyHistoryFilters();
});
document.getElementById('typeFilter').addEventListener('change', (e) => {
  hState.placeType = e.target.value;
  applyHistoryFilters();
});
document.getElementById('statusFilter').addEventListener('change', (e) => {
  hState.status = e.target.value;
  applyHistoryFilters();
});

function renderHistory(data){
  hState.data = data;
  document.getElementById('historyEmpty').style.display = 'none';
  document.getElementById('historyContent').style.display = '';
  const indexes = buildIndexes(data);
  renderHeader(data);
  renderMap(data);
  populateTypeFilter(data);
  renderEras(data, indexes);
  renderResidents(data);
  applyHistoryFilters();
}

function pollHistoryLog(){
  fetch('/api/history/log?since=' + hState.logSince).then(r => r.json()).then(d => {
    if (d.lines && d.lines.length) {
      const pre = document.getElementById('historyLog');
      const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 20;
      d.lines.forEach(line => { pre.textContent += (pre.textContent ? '\n' : '') + line; });
      if (atBottom) pre.scrollTop = pre.scrollHeight;
    }
    hState.logSince = d.next;
  }).catch(() => {});
}

function pollHistoryStatus(){
  fetch('/api/history/status').then(r => r.json()).then(d => {
    const phase = d.phase || 'idle';
    historyStatusPill.className = 'status-pill ' + phase;
    historyStatusText.textContent = phase;
    historyErrorMsg.textContent = d.error || '';
    generateBtn.disabled = phase === 'running';

    if (phase !== 'idle') {
      document.getElementById('historyEmpty').style.display = 'none';
      document.getElementById('historyLogPanel').style.display = '';
      pollHistoryLog();
    }

    if (phase === 'done' && hState.lastPhase !== 'done') {
      fetch('/api/history/data').then(r => r.json()).then(renderHistory);
    }
    hState.lastPhase = phase;
  }).catch(() => {});
}

setInterval(pollHistoryStatus, 1200);
pollHistoryStatus();

generateBtn.addEventListener('click', () => {
  const payload = {
    seed: parseIntOrNull(document.getElementById('seedInput').value),
    figures_per_era: parseIntOrNull(document.getElementById('figuresInput').value),
    events_per_figure: parseIntOrNull(document.getElementById('eventsInput').value),
    characters: parseIntOrNull(document.getElementById('charactersInput').value) || 10,
    no_llm: document.getElementById('noLlmInput').checked,
  };
  fetch('/api/history/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => r.json()).then(d => {
    if (!d.ok) { historyErrorMsg.textContent = d.error || 'could not start generation'; return; }
    hState.logSince = 0;
    document.getElementById('historyLog').textContent = '';
    pollHistoryStatus();
  });
});
