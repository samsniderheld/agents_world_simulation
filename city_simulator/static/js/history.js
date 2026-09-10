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

function renderSummary(data){
  const plate = document.getElementById('summaryPlate');
  if (!data.summary) { plate.style.display = 'none'; return; }
  plate.style.display = '';
  document.getElementById('summaryText').textContent = data.summary;
}

// ======================================================================
// Interactive city map -- canvas rendering of map.graphic (dark water,
// block-textured land, white district borders, labels, numbered place
// markers), with hover highlighting and click-through to detail modals.
// LLM-drawn maps have no structural data, so they fall back to the <pre>.
// ======================================================================

const cityMap = {
  G: null,          // map.graphic
  map: null,        // the whole map dict
  base: null,       // offscreen canvas holding the fully-drawn base map
  markers: [],      // {x, y, r, place_id, number} in canvas px
  hoverNid: null,
  nidDots: {},      // nid -> [[row, colStart, colEnd], ...] runs, built lazily
  numberByPlaceId: {},
  hoodById: {},
};
const CITY_SCALE = 6; // canvas px per map dot

function renderMap(data){
  const map = data.map;
  const canvas = document.getElementById('cityCanvas');
  const pre = document.getElementById('mapText');
  const hint = document.getElementById('cityMapHint');
  document.getElementById('mapCaption').textContent = (map && map.caption) || '';

  if (!map || typeof map !== 'object' || !map.graphic) {
    canvas.style.display = 'none';
    hint.style.display = 'none';
    pre.style.display = '';
    pre.textContent = map ? (map.body || map.text || '') : (map || '');
    document.getElementById('neighborhoodKey').innerHTML = '';
    return;
  }

  pre.style.display = 'none';
  canvas.style.display = '';
  hint.style.display = '';
  buildCityMap(map, data);

  const keyEl = document.getElementById('neighborhoodKey');
  keyEl.innerHTML = (map.neighborhoods || []).map(n =>
    `<span class="entry" data-nid="${escapeHtml(n.id || '')}"><span class="swatch" style="background:${n.color}"></span>${escapeHtml(n.name)}</span>`
  ).join('');
  keyEl.querySelectorAll('.entry[data-nid]').forEach(el => {
    el.addEventListener('click', () => openNeighborhoodModal(el.dataset.nid));
  });
}

function cityLand(r, c){
  const G = cityMap.G;
  if (r < 0 || c < 0 || r >= G.dot_height || c >= G.dot_width) return false;
  return G.land[r][c] === '1';
}

function cityNid(r, c){
  if (!cityLand(r, c)) return null;
  const G = cityMap.G;
  // Walk the wavy boundary curves: which era band (top to bottom) and
  // which west-east column this dot falls in -- same logic as the Python
  // side's _dot_era_index/_dot_col_index, so borders match exactly.
  let b = 0;
  while (b < G.era_boundaries.length && r >= G.era_boundaries[b][c]) b++;
  let j = 0;
  while (j < G.column_boundaries.length && c >= G.column_boundaries[j][r]) j++;
  return `${G.band_eras[b]}_${j}`;
}

// Deterministic per-cell pseudo-random, so the block texture doesn't
// reshuffle on every redraw.
function cityRand(x, y){
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return s - Math.floor(s);
}

function buildCityMap(map, data){
  const G = map.graphic;
  const S = CITY_SCALE;
  cityMap.G = G;
  cityMap.map = map;
  cityMap.hoverNid = null;
  cityMap.nidDots = {};

  cityMap.hoodById = {};
  cityMap.numberByPlaceId = {};
  let n = 1;
  (map.neighborhoods || []).forEach(h => {
    cityMap.hoodById[h.id] = h;
    (h.place_ids || []).forEach(pid => { cityMap.numberByPlaceId[pid] = n++; });
  });

  const canvas = document.getElementById('cityCanvas');
  canvas.width = G.dot_width * S;
  canvas.height = G.dot_height * S;

  const base = document.createElement('canvas');
  base.width = canvas.width;
  base.height = canvas.height;
  const ctx = base.getContext('2d');

  // --- water ---
  ctx.fillStyle = '#0c1014';
  ctx.fillRect(0, 0, base.width, base.height);

  // --- faint coast glow: water dots near land get a lighter wash ---
  for (let r = 0; r < G.dot_height; r++) {
    for (let c = 0; c < G.dot_width; c++) {
      if (cityLand(r, c)) continue;
      let near1 = false, near2 = false;
      for (let dr = -2; dr <= 2 && !near1; dr++) {
        for (let dc = -2; dc <= 2; dc++) {
          if (!cityLand(r + dr, c + dc)) continue;
          if (Math.max(Math.abs(dr), Math.abs(dc)) <= 1) { near1 = true; break; }
          near2 = true;
        }
      }
      if (near1) ctx.fillStyle = 'rgba(140,175,205,0.10)';
      else if (near2) ctx.fillStyle = 'rgba(140,175,205,0.05)';
      else continue;
      ctx.fillRect(c * S, r * S, S, S);
    }
  }

  // --- land base (dark asphalt under the blocks = the streets) ---
  ctx.fillStyle = '#23272d';
  for (let r = 0; r < G.dot_height; r++) {
    let c = 0;
    while (c < G.dot_width) {
      if (!cityLand(r, c)) { c++; continue; }
      let end = c;
      while (end < G.dot_width && cityLand(r, end)) end++;
      ctx.fillRect(c * S, r * S, (end - c) * S, S);
      c = end;
    }
  }

  // --- city blocks: a jittered grid of light-gray rects with 1-dot
  // street gaps; blocks straddling the coast render per-dot so the
  // coastline stays ragged; occasional block becomes a park ---
  const PX = 5, PY = 4;  // block pitch in dots (4x3 block + 1-dot street)
  for (let by = 0; by * PY < G.dot_height; by++) {
    for (let bx = 0; bx * PX < G.dot_width; bx++) {
      const r0 = by * PY, c0 = bx * PX;
      let landCount = 0, total = 0;
      for (let dr = 0; dr < PY - 1; dr++) {
        for (let dc = 0; dc < PX - 1; dc++) {
          if (r0 + dr >= G.dot_height || c0 + dc >= G.dot_width) continue;
          total++;
          if (cityLand(r0 + dr, c0 + dc)) landCount++;
        }
      }
      if (!total || !landCount) continue;
      const rnd = cityRand(bx, by);
      if (landCount === total) {
        if (rnd < 0.06) {
          ctx.fillStyle = '#2e3c31';  // park
        } else {
          const v = Math.round(150 + cityRand(bx * 3 + 1, by * 7 + 2) * 55);
          ctx.fillStyle = `rgb(${v},${v + 2},${v + 4})`;
        }
        ctx.fillRect(c0 * S, r0 * S, (PX - 1) * S, (PY - 1) * S);
      } else {
        // coastal block -- draw only its land dots, dimmer
        ctx.fillStyle = '#6d7278';
        for (let dr = 0; dr < PY - 1; dr++) {
          for (let dc = 0; dc < PX - 1; dc++) {
            if (cityLand(r0 + dr, c0 + dc)) ctx.fillRect((c0 + dc) * S, (r0 + dr) * S, S, S);
          }
        }
      }
    }
  }

  // --- district borders: white lines wherever the neighborhood id
  // changes between adjacent dots (including land/water = the coast) ---
  ctx.strokeStyle = 'rgba(244,247,250,0.9)';
  ctx.lineWidth = 2;
  ctx.beginPath();
  for (let r = 0; r < G.dot_height; r++) {
    for (let c = 0; c < G.dot_width; c++) {
      const id = cityNid(r, c);
      const idR = c + 1 < G.dot_width ? cityNid(r, c + 1) : null;
      const idB = r + 1 < G.dot_height ? cityNid(r + 1, c) : null;
      if (id !== idR && (id !== null || idR !== null)) {
        ctx.moveTo((c + 1) * S, r * S);
        ctx.lineTo((c + 1) * S, (r + 1) * S);
      }
      if (id !== idB && (id !== null || idB !== null)) {
        ctx.moveTo(c * S, (r + 1) * S);
        ctx.lineTo((c + 1) * S, (r + 1) * S);
      }
    }
  }
  ctx.stroke();

  // --- river labels + compass ---
  ctx.fillStyle = 'rgba(150,180,205,0.5)';
  ctx.font = `600 ${2.2 * S}px ${getComputedStyle(document.body).getPropertyValue('--mono') || 'monospace'}`;
  ctx.textAlign = 'center';
  ctx.save();
  ctx.translate(2.2 * S, base.height / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('H U D S O N   R I V E R', 0, 0);
  ctx.restore();
  ctx.save();
  ctx.translate(base.width - 1.2 * S, base.height / 2);
  ctx.rotate(Math.PI / 2);
  ctx.fillText('E A S T   R I V E R', 0, 0);
  ctx.restore();
  ctx.textAlign = 'left';
  ctx.fillText('N ↑', 1.5 * S, 3 * S);

  // --- neighborhood name labels, reference-style: bold condensed
  // uppercase white, one word per line, heavy dark shadow ---
  (map.neighborhoods || []).forEach(h => {
    if (!h.centroid) return;
    const x = (h.centroid.col * 2 + 1) * S;
    const y = (h.centroid.row * 4 + 2) * S;
    const words = h.name.toUpperCase().split(/\s+/);
    // group short words so a multi-word name doesn't become a tower of
    // single words
    const lines = [];
    words.forEach(w => {
      if (lines.length && (lines[lines.length - 1] + ' ' + w).length <= 12) {
        lines[lines.length - 1] += ' ' + w;
      } else lines.push(w);
    });
    // Each era band is only ~1/8th of the map tall -- long fallback names
    // ("West Progressive Era & Tenement City Quarter") have to shrink to
    // stay inside their own district instead of papering over neighbors.
    const fontPx = (lines.length >= 4 ? 1.9 : lines.length === 3 ? 2.2 : 2.8) * S;
    const lineStep = fontPx * 1.04;
    ctx.font = `800 ${fontPx}px 'Arial Narrow', 'Helvetica Neue', sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.shadowColor = 'rgba(0,0,0,0.95)';
    ctx.shadowBlur = 6;
    // keep the whole block on-canvas (top-band centroids sit near the edge)
    let y0 = y - ((lines.length - 1) * lineStep) / 2;
    y0 = Math.max(fontPx * 0.7, Math.min(y0, base.height - fontPx * 0.7 - (lines.length - 1) * lineStep));
    lines.forEach((line, i) => {
      ctx.lineWidth = 3;
      ctx.strokeStyle = 'rgba(10,12,14,0.85)';
      ctx.strokeText(line, x, y0 + i * lineStep);
      ctx.fillStyle = '#f2f4f6';
      ctx.fillText(line, x, y0 + i * lineStep);
    });
    ctx.shadowBlur = 0;
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
  });

  // --- numbered place markers ---
  cityMap.markers = (G.markers || []).map(m => {
    const x = (m.col * 2 + 1) * S;
    const y = (m.row * 4 + 2) * S;
    return { x, y, r: 1.9 * S, place_id: m.place_id, number: m.number };
  });
  cityMap.markers.forEach(m => {
    ctx.beginPath();
    ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2);
    ctx.fillStyle = '#f2f4f6';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#0c1014';
    ctx.stroke();
    ctx.fillStyle = '#14181d';
    ctx.font = `700 ${1.9 * S}px ${getComputedStyle(document.body).getPropertyValue('--mono') || 'monospace'}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(m.number), m.x, m.y + 1);
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
  });

  cityMap.base = base;
  drawCityMap();
}

function nidDotRuns(nid){
  if (cityMap.nidDots[nid]) return cityMap.nidDots[nid];
  const G = cityMap.G;
  const runs = [];
  for (let r = 0; r < G.dot_height; r++) {
    let c = 0;
    while (c < G.dot_width) {
      if (cityNid(r, c) !== nid) { c++; continue; }
      let end = c;
      while (end < G.dot_width && cityNid(r, end) === nid) end++;
      runs.push([r, c, end]);
      c = end;
    }
  }
  cityMap.nidDots[nid] = runs;
  return runs;
}

function drawCityMap(){
  const canvas = document.getElementById('cityCanvas');
  const ctx = canvas.getContext('2d');
  ctx.drawImage(cityMap.base, 0, 0);
  const nid = cityMap.hoverNid;
  if (nid && cityMap.hoodById[nid]) {
    const S = CITY_SCALE;
    ctx.fillStyle = cityMap.hoodById[nid].color;
    ctx.globalAlpha = 0.22;
    nidDotRuns(nid).forEach(([r, c, end]) => ctx.fillRect(c * S, r * S, (end - c) * S, S));
    ctx.globalAlpha = 1;
  }
}

function cityMapEventPos(e){
  const canvas = document.getElementById('cityCanvas');
  const rect = canvas.getBoundingClientRect();
  const x = (e.clientX - rect.left) * (canvas.width / rect.width);
  const y = (e.clientY - rect.top) * (canvas.height / rect.height);
  return { x, y };
}

function cityMarkerAt(x, y){
  return cityMap.markers.find(m => Math.hypot(m.x - x, m.y - y) <= m.r + 3) || null;
}

document.getElementById('cityCanvas').addEventListener('mousemove', (e) => {
  if (!cityMap.base) return;
  const { x, y } = cityMapEventPos(e);
  const canvas = document.getElementById('cityCanvas');
  const marker = cityMarkerAt(x, y);
  const nid = marker ? null : cityNid(Math.floor(y / CITY_SCALE), Math.floor(x / CITY_SCALE));
  canvas.style.cursor = (marker || nid) ? 'pointer' : 'default';
  if (nid !== cityMap.hoverNid) {
    cityMap.hoverNid = nid;
    drawCityMap();
  }
});

document.getElementById('cityCanvas').addEventListener('mouseleave', () => {
  if (!cityMap.base) return;
  if (cityMap.hoverNid !== null) { cityMap.hoverNid = null; drawCityMap(); }
});

document.getElementById('cityCanvas').addEventListener('click', (e) => {
  if (!cityMap.base) return;
  const { x, y } = cityMapEventPos(e);
  const marker = cityMarkerAt(x, y);
  if (marker) { openPlaceModal(marker.place_id, null); return; }
  const nid = cityNid(Math.floor(y / CITY_SCALE), Math.floor(x / CITY_SCALE));
  if (nid) openNeighborhoodModal(nid);
});

// --- detail modals ----------------------------------------------------

function openCityModal(html){
  document.getElementById('cityModal').innerHTML = html;
  document.getElementById('cityModalOverlay').style.display = '';
}

function closeCityModal(){
  document.getElementById('cityModalOverlay').style.display = 'none';
}

document.getElementById('cityModalOverlay').addEventListener('click', (e) => {
  if (e.target === document.getElementById('cityModalOverlay')) closeCityModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeCityModal();
});

function openNeighborhoodModal(nid){
  const hood = cityMap.hoodById[nid];
  const data = hState.data;
  if (!hood || !data) return;
  const era = data.eras.find(er => er.id === hood.era_id);
  const placesById = new Map(data.places.map(p => [p.id, p]));
  const hoodPlaces = (hood.place_ids || []).map(pid => placesById.get(pid)).filter(Boolean);
  const eventCount = hoodPlaces.reduce((sum, p) => sum + p.history.length, 0);
  const figures = data.figures.filter(f => f.era_id === hood.era_id);

  const placeRows = hoodPlaces.map(p => {
    const num = cityMap.numberByPlaceId[p.id];
    const statusText = p.status === 'active'
      ? `founded ${p.founded_year}`
      : `founded ${p.founded_year}, ${p.status}${p.closed_year ? ' ' + p.closed_year : ''}`;
    return `
      <div class="modal-row clickable" data-place="${escapeHtml(p.id)}">
        <span class="row-num">${num ? '[' + num + ']' : ''}</span>
        <span class="row-main">${escapeHtml(p.name)}</span>
        <span class="row-sub">${escapeHtml(p.place_type)} · ${statusText}</span>
      </div>`;
  }).join('') || '<div class="modal-empty">No places were founded in this neighborhood.</div>';

  const figureRows = figures.map(f => {
    const lifespan = f.death_year ? `${f.birth_year}–${f.death_year}` : `b. ${f.birth_year}`;
    return `<div class="modal-row"><span class="row-main">${escapeHtml(f.name)}</span><span class="row-sub">${escapeHtml(f.role)} (${lifespan})</span></div>`;
  }).join('');

  openCityModal(`
    <div class="modal-header" style="border-left-color:${hood.color}">
      <button class="modal-close" data-close>×</button>
      <h3>${escapeHtml(hood.name)}</h3>
      <div class="modal-sub">${era ? escapeHtml(era.name) + ' · ' + era.start_year + '–' + era.end_year + ' · ' : ''}${escapeHtml(hood.column)} side</div>
    </div>
    ${era ? `<div class="modal-desc">${escapeHtml(era.description)}</div>` : ''}
    <div class="modal-stats">
      <span>${hoodPlaces.length} place${hoodPlaces.length === 1 ? '' : 's'}</span>
      <span>${eventCount} recorded event${eventCount === 1 ? '' : 's'}</span>
      <span>${figures.length} era figure${figures.length === 1 ? '' : 's'}</span>
    </div>
    <div class="modal-section-label">Places</div>
    ${placeRows}
    ${figures.length ? `<details class="modal-figures"><summary>Notable figures of this era</summary>${figureRows}</details>` : ''}
  `);

  const modal = document.getElementById('cityModal');
  modal.querySelector('[data-close]').addEventListener('click', closeCityModal);
  modal.querySelectorAll('[data-place]').forEach(el => {
    el.addEventListener('click', () => openPlaceModal(el.dataset.place, nid));
  });
}

function openPlaceModal(placeId, fromNid){
  const data = hState.data;
  if (!data) return;
  const place = data.places.find(p => p.id === placeId);
  if (!place) return;
  const figuresById = new Map(data.figures.map(f => [f.id, f]));
  const founder = figuresById.get(place.founding_figure_id);
  const owner = figuresById.get(place.current_owner_figure_id);
  const num = cityMap.numberByPlaceId[placeId];
  const statusText = place.status === 'active'
    ? 'still active'
    : `${place.status}${place.closed_year ? ' ' + place.closed_year : ''}`;

  const timeline = place.history.map(h =>
    `<div class="modal-event"><span class="year">${h.year}</span>${escapeHtml(h.gospel_text)}</div>`
  ).join('') || '<div class="modal-empty">No recorded events.</div>';

  openCityModal(`
    <div class="modal-header">
      <button class="modal-close" data-close>×</button>
      ${fromNid ? '<button class="modal-back" data-back>‹ back</button>' : ''}
      <h3>${num ? '[' + num + '] ' : ''}${escapeHtml(place.name)}</h3>
      <div class="modal-sub">${escapeHtml(place.place_type)} · domain: ${escapeHtml(place.domain)}</div>
    </div>
    <div class="modal-stats">
      <span>founded ${place.founded_year}</span>
      <span>${statusText}</span>
      ${founder ? `<span>founded by ${escapeHtml(founder.name)}</span>` : ''}
      ${owner && owner !== founder ? `<span>last held by ${escapeHtml(owner.name)}</span>` : ''}
    </div>
    <div class="modal-section-label">History</div>
    ${timeline}
  `);

  const modal = document.getElementById('cityModal');
  modal.querySelector('[data-close]').addEventListener('click', closeCityModal);
  const back = modal.querySelector('[data-back]');
  if (back) back.addEventListener('click', () => openNeighborhoodModal(fromNid));
}

// --- 1950s subway-map image (via the Visuals tab's fal-backed job slot) ---

function resetSubwayMap(){
  document.getElementById('subwayMapStatus').textContent = '';
  document.getElementById('subwayMapPlate').style.display = 'none';
  document.getElementById('subwayMapHideBtn').style.display = 'none';
  document.getElementById('subwayMapBtn').disabled = false;
  document.getElementById('subwayMapBtn').textContent = '🚇 Generate 1950s Subway Map (via fal)';
}

function showSubwayMap(url){
  document.getElementById('subwayMapImg').src = '/api/visuals/files/' + url;
  document.getElementById('subwayMapPlate').style.display = '';
  document.getElementById('subwayMapHideBtn').style.display = '';
  document.getElementById('subwayMapBtn').textContent = '🚇 Regenerate Subway Map (via fal)';
}

function pollSubwayMap(){
  const statusEl = document.getElementById('subwayMapStatus');
  fetch('/api/visuals/status').then(r => r.json()).then(d => {
    const phase = d.phase || 'idle';
    if (phase === 'running') { setTimeout(pollSubwayMap, 1500); return; }
    document.getElementById('subwayMapBtn').disabled = false;
    if (phase === 'error') { statusEl.textContent = d.error || 'generation failed'; return; }
    if (phase !== 'done') { statusEl.textContent = ''; return; }
    fetch('/api/visuals/result').then(r => r.json()).then(result => {
      if (result.kind !== 'subway_map') return;  // some other visuals job finished first
      if (!result.images || !result.images.length) {
        statusEl.textContent = 'no image came back';
        return;
      }
      statusEl.textContent = '';
      showSubwayMap(result.images[0].url);
    });
  }).catch(() => {
    statusEl.textContent = 'lost contact with the server';
  });
}

document.getElementById('subwayMapBtn').addEventListener('click', () => {
  const mapText = hState.data && hState.data.map && hState.data.map.text;
  if (!mapText) return;
  const statusEl = document.getElementById('subwayMapStatus');
  document.getElementById('subwayMapBtn').disabled = true;
  statusEl.textContent = 'starting…';
  fetch('/api/visuals/generate-subway-map', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ map_text: mapText }),
  }).then(r => r.json()).then(d => {
    if (!d.ok) {
      document.getElementById('subwayMapBtn').disabled = false;
      statusEl.textContent = d.error || 'could not start generation';
      return;
    }
    statusEl.textContent = 'generating (this can take a minute)…';
    pollSubwayMap();
  });
});

document.getElementById('subwayMapHideBtn').addEventListener('click', () => {
  const plate = document.getElementById('subwayMapPlate');
  const hideBtn = document.getElementById('subwayMapHideBtn');
  const hidden = plate.style.display === 'none';
  plate.style.display = hidden ? '' : 'none';
  hideBtn.textContent = hidden ? 'Hide Subway Map' : 'Show Subway Map';
});

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

// --- per-entity media (attached images/video, see citystate/store.py) --

function entityMediaList(entityId){
  return (hState.data && hState.data.media && hState.data.media[entityId]) || [];
}

function latestImagePath(entityId){
  const images = entityMediaList(entityId).filter(m => m.kind === 'image');
  return images.length ? images[images.length - 1].local_path : null;
}

function entityThumbHtml(item){
  const media = item.kind === 'video'
    ? `<video src="${fileUrl(item.url)}" muted loop playsinline></video>`
    : `<img src="${fileUrl(item.url)}" alt="${escapeHtml(item.prompt)}" />`;
  return `<div class="entity-thumb">${media}<button class="entity-thumb-remove" data-remove-media="${escapeHtml(item.id)}" title="Remove">×</button></div>`;
}

// Rendered once as part of the card's own HTML, then refreshed in place
// (see refreshEntityMediaDom) after a generation completes, so the rest
// of the card -- and any other entity's expanded form -- isn't disturbed.
function entityMediaHtml(entityId, entityType, promptHint){
  const items = entityMediaList(entityId);
  const hasImage = items.some(m => m.kind === 'image');
  return `
    <div class="entity-media" data-entity-id="${escapeHtml(entityId)}" data-entity-type="${entityType}">
      <div class="entity-media-thumbs">
        ${items.map(entityThumbHtml).join('')}
        <button class="entity-media-toggle" data-action="toggle-media-form">+ Media</button>
      </div>
      <div class="entity-media-form" hidden>
        <input type="text" class="media-prompt-input" placeholder="${escapeHtml(promptHint)}" />
        <div class="media-form-actions">
          <button data-action="gen-image">Generate Image</button>
          <button data-action="gen-video" ${hasImage ? '' : 'disabled title="Add an image first"'}>Animate Latest Image</button>
        </div>
        <span class="media-status"></span>
      </div>
    </div>
  `;
}

function refreshEntityMediaDom(entityId){
  document.querySelectorAll(`.entity-media[data-entity-id="${CSS.escape(entityId)}"]`).forEach(wrap => {
    const entityType = wrap.dataset.entityType;
    const promptHint = wrap.querySelector('.media-prompt-input').placeholder;
    const temp = document.createElement('div');
    temp.innerHTML = entityMediaHtml(entityId, entityType, promptHint);
    wrap.replaceWith(temp.firstElementChild);
  });
}

document.addEventListener('click', (e) => {
  const toggleBtn = e.target.closest('[data-action="toggle-media-form"]');
  if (toggleBtn) {
    const form = toggleBtn.closest('.entity-media').querySelector('.entity-media-form');
    form.hidden = !form.hidden;
    return;
  }

  const removeBtn = e.target.closest('[data-remove-media]');
  if (removeBtn) {
    const wrap = removeBtn.closest('.entity-media');
    const entityId = wrap.dataset.entityId;
    fetch(`/api/city/media/${encodeURIComponent(entityId)}/${encodeURIComponent(removeBtn.dataset.removeMedia)}`, {
      method: 'DELETE',
    }).then(r => r.json()).then(d => {
      if (!d.ok) return;
      const list = entityMediaList(entityId).filter(m => m.id !== removeBtn.dataset.removeMedia);
      hState.data.media[entityId] = list;
      refreshEntityMediaDom(entityId);
    });
    return;
  }

  const genBtn = e.target.closest('[data-action="gen-image"], [data-action="gen-video"]');
  if (genBtn) {
    const wrap = genBtn.closest('.entity-media');
    const promptInput = wrap.querySelector('.media-prompt-input');
    const prompt = promptInput.value.trim();
    const statusEl = wrap.querySelector('.media-status');
    if (!prompt) { statusEl.textContent = 'enter a description first'; return; }
    startEntityMediaGeneration(wrap.dataset.entityId, genBtn.dataset.action === 'gen-video' ? 'video' : 'image', prompt, wrap);
  }
});

function startEntityMediaGeneration(entityId, kind, prompt, wrap){
  const statusEl = wrap.querySelector('.media-status');
  const buttons = wrap.querySelectorAll('button');
  buttons.forEach(b => b.disabled = true);
  statusEl.textContent = 'starting…';

  let endpoint, payload;
  if (kind === 'video') {
    const sourcePath = latestImagePath(entityId);
    if (!sourcePath) {
      statusEl.textContent = 'add an image first';
      buttons.forEach(b => b.disabled = false);
      return;
    }
    endpoint = '/api/visuals/generate-video';
    payload = { prompt, image_path: sourcePath, options: {} };
  } else {
    endpoint = '/api/visuals/generate-image';
    payload = { prompt, image_paths: null, options: {} };
  }

  fetch(endpoint, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }).then(r => r.json()).then(d => {
    if (!d.ok) {
      statusEl.textContent = d.error || 'could not start generation';
      buttons.forEach(b => b.disabled = false);
      return;
    }
    statusEl.textContent = 'generating (this can take a minute)…';
    pollEntityMediaJob(entityId, kind, prompt, wrap);
  });
}

function pollEntityMediaJob(entityId, kind, prompt, wrap){
  const statusEl = wrap.querySelector('.media-status');
  fetch('/api/visuals/status').then(r => r.json()).then(d => {
    const phase = d.phase || 'idle';
    if (phase === 'running') { setTimeout(() => pollEntityMediaJob(entityId, kind, prompt, wrap), 1500); return; }
    wrap.querySelectorAll('button').forEach(b => b.disabled = false);
    if (phase === 'error') { statusEl.textContent = d.error || 'generation failed'; return; }
    if (phase !== 'done') { statusEl.textContent = ''; return; }
    fetch('/api/visuals/result').then(r => r.json()).then(result => {
      const media = result.kind === 'image' && result.images && result.images.length ? result.images[0]
        : result.kind === 'video' && result.video ? result.video
        : null;
      if (!media) return;  // some other visuals job finished first -- not ours
      fetch('/api/city/media', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity_id: entityId, kind, url: media.url, local_path: media.local_path, prompt }),
      }).then(r => r.json()).then(cityRes => {
        if (!cityRes.ok) { statusEl.textContent = cityRes.error || 'could not attach media'; return; }
        if (!hState.data.media) hState.data.media = {};
        hState.data.media[entityId] = cityRes.media;
        refreshEntityMediaDom(entityId);
      });
    });
  }).catch(() => {
    statusEl.textContent = 'lost contact with the server';
    wrap.querySelectorAll('button').forEach(b => b.disabled = false);
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
      ${entityMediaHtml(place.id, 'place', `Describe a photo of ${place.name}…`)}
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
      ${person.id ? entityMediaHtml(person.id, 'character', `Describe a portrait of ${person.name}…`) : ''}
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
  renderSummary(data);
  renderMap(data);
  resetSubwayMap();
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

function startHistoryGeneration(confirmOverwrite){
  const payload = {
    seed: parseIntOrNull(document.getElementById('seedInput').value),
    figures_per_era: parseIntOrNull(document.getElementById('figuresInput').value),
    events_per_figure: parseIntOrNull(document.getElementById('eventsInput').value),
    characters: parseIntOrNull(document.getElementById('charactersInput').value) || 10,
    no_llm: document.getElementById('noLlmInput').checked,
    llm_map: document.getElementById('llmMapInput').checked,
    confirm_overwrite: !!confirmOverwrite,
  };
  fetch('/api/history/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).then(r => r.json()).then(d => {
    if (!d.ok) {
      if (d.needs_confirmation) {
        if (confirm('A saved city already exists and will be permanently replaced. Continue?')) {
          startHistoryGeneration(true);
        }
        return;
      }
      historyErrorMsg.textContent = d.error || 'could not start generation';
      return;
    }
    hState.logSince = 0;
    document.getElementById('historyLog').textContent = '';
    pollHistoryStatus();
  });
}

generateBtn.addEventListener('click', () => startHistoryGeneration(false));
