"use strict";

// ======================================================================
// Shared interactive city map -- canvas rendering of a history payload's
// map.graphic (dark water, block-textured land, white district borders,
// labels, numbered place markers), with hover highlighting and click-
// through to detail modals. Used by both the History tab (place markers
// only) and the Agents tab (place markers + a second agent-marker layer,
// see buildCityMap's opts.extraMarkers).
//
// One cm ("city map") instance per <canvas> -- createCityMap() makes one,
// buildCityMap() (re)draws it from a map payload, attachCityMapEvents()
// wires its mouse handling exactly once. LLM-drawn maps have no
// map.graphic at all; callers fall back to plain text in that case (see
// history.js's renderMap()).
// ======================================================================

const CITY_SCALE = 6; // canvas px per map dot

function monoFont(){
  return getComputedStyle(document.body).getPropertyValue('--mono') || 'monospace';
}

function createCityMap(canvas){
  return {
    canvas, G: null, map: null, base: null,
    markers: [],        // place markers, from map.graphic.markers
    extraMarkers: [],   // e.g. agent markers -- {row, col, dx, dy, color, label, onClick}
    hoverNid: null,
    nidDots: {},
    hoodById: {},
    numberByPlaceId: {},
    onPlaceClick: null,        // (cm, marker) => void
    onNeighborhoodClick: null, // (cm, nid) => void
    _attached: false,
  };
}

function cmLand(cm, r, c){
  const G = cm.G;
  if (r < 0 || c < 0 || r >= G.dot_height || c >= G.dot_width) return false;
  return G.land[r][c] === '1';
}

function cmNid(cm, r, c){
  if (!cmLand(cm, r, c)) return null;
  const G = cm.G;
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
function cmRand(x, y){
  const s = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
  return s - Math.floor(s);
}

function buildCityMap(cm, map, opts = {}){
  const G = map.graphic;
  const S = CITY_SCALE;
  cm.G = G;
  cm.map = map;
  cm.hoverNid = null;
  cm.nidDots = {};
  cm.onPlaceClick = opts.onPlaceClick || null;
  cm.onNeighborhoodClick = opts.onNeighborhoodClick || null;
  cm.extraMarkers = opts.extraMarkers || [];

  cm.hoodById = {};
  cm.numberByPlaceId = {};
  let n = 1;
  (map.neighborhoods || []).forEach(h => {
    cm.hoodById[h.id] = h;
    (h.place_ids || []).forEach(pid => { cm.numberByPlaceId[pid] = n++; });
  });

  const canvas = cm.canvas;
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
      if (cmLand(cm, r, c)) continue;
      let near1 = false, near2 = false;
      for (let dr = -2; dr <= 2 && !near1; dr++) {
        for (let dc = -2; dc <= 2; dc++) {
          if (!cmLand(cm, r + dr, c + dc)) continue;
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
      if (!cmLand(cm, r, c)) { c++; continue; }
      let end = c;
      while (end < G.dot_width && cmLand(cm, r, end)) end++;
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
          if (cmLand(cm, r0 + dr, c0 + dc)) landCount++;
        }
      }
      if (!total || !landCount) continue;
      const rnd = cmRand(bx, by);
      if (landCount === total) {
        if (rnd < 0.06) {
          ctx.fillStyle = '#2e3c31';  // park
        } else {
          const v = Math.round(150 + cmRand(bx * 3 + 1, by * 7 + 2) * 55);
          ctx.fillStyle = `rgb(${v},${v + 2},${v + 4})`;
        }
        ctx.fillRect(c0 * S, r0 * S, (PX - 1) * S, (PY - 1) * S);
      } else {
        // coastal block -- draw only its land dots, dimmer
        ctx.fillStyle = '#6d7278';
        for (let dr = 0; dr < PY - 1; dr++) {
          for (let dc = 0; dc < PX - 1; dc++) {
            if (cmLand(cm, r0 + dr, c0 + dc)) ctx.fillRect((c0 + dc) * S, (r0 + dr) * S, S, S);
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
      const id = cmNid(cm, r, c);
      const idR = c + 1 < G.dot_width ? cmNid(cm, r, c + 1) : null;
      const idB = r + 1 < G.dot_height ? cmNid(cm, r + 1, c) : null;
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
  ctx.font = `600 ${2.2 * S}px ${monoFont()}`;
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
  cm.markers = (G.markers || []).map(m => {
    const x = (m.col * 2 + 1) * S;
    const y = (m.row * 4 + 2) * S;
    return { x, y, r: 1.9 * S, place_id: m.place_id, number: m.number };
  });
  cm.markers.forEach(m => {
    ctx.beginPath();
    ctx.arc(m.x, m.y, m.r, 0, Math.PI * 2);
    ctx.fillStyle = '#f2f4f6';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#0c1014';
    ctx.stroke();
    ctx.fillStyle = '#14181d';
    ctx.font = `700 ${1.9 * S}px ${monoFont()}`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(m.number), m.x, m.y + 1);
    ctx.textBaseline = 'alphabetic';
    ctx.textAlign = 'left';
  });

  // --- extra markers (e.g. agents), drawn on top of place markers ---
  cm.extraMarkers.forEach(m => {
    const x = (m.col * 2 + 1) * S + (m.dx || 0);
    const y = (m.row * 4 + 2) * S + (m.dy || 0);
    m._x = x; m._y = y; m._r = 1.6 * S;
    ctx.beginPath();
    ctx.arc(x, y, m._r, 0, Math.PI * 2);
    ctx.fillStyle = m.color || '#f5c451';
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#0c1014';
    ctx.stroke();
    if (m.label) {
      ctx.fillStyle = '#0c1014';
      ctx.font = `700 ${1.5 * S}px ${monoFont()}`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(m.label, x, y + 1);
      ctx.textBaseline = 'alphabetic';
      ctx.textAlign = 'left';
    }
  });

  cm.base = base;
  drawCityMap(cm);
  if (!cm._attached) {
    attachCityMapEvents(cm);
    cm._attached = true;
  }
}

function nidDotRuns(cm, nid){
  if (cm.nidDots[nid]) return cm.nidDots[nid];
  const G = cm.G;
  const runs = [];
  for (let r = 0; r < G.dot_height; r++) {
    let c = 0;
    while (c < G.dot_width) {
      if (cmNid(cm, r, c) !== nid) { c++; continue; }
      let end = c;
      while (end < G.dot_width && cmNid(cm, r, end) === nid) end++;
      runs.push([r, c, end]);
      c = end;
    }
  }
  cm.nidDots[nid] = runs;
  return runs;
}

function drawCityMap(cm){
  const ctx = cm.canvas.getContext('2d');
  ctx.drawImage(cm.base, 0, 0);
  const nid = cm.hoverNid;
  if (nid && cm.hoodById[nid]) {
    const S = CITY_SCALE;
    ctx.fillStyle = cm.hoodById[nid].color;
    ctx.globalAlpha = 0.22;
    nidDotRuns(cm, nid).forEach(([r, c, end]) => ctx.fillRect(c * S, r * S, (end - c) * S, S));
    ctx.globalAlpha = 1;
  }
}

function cmEventPos(cm, e){
  const rect = cm.canvas.getBoundingClientRect();
  const x = (e.clientX - rect.left) * (cm.canvas.width / rect.width);
  const y = (e.clientY - rect.top) * (cm.canvas.height / rect.height);
  return { x, y };
}

// Agent (extra) markers are drawn on top, so they're checked first --
// otherwise an agent standing exactly on their place's marker would be
// unreachable by click.
function cmMarkerAt(cm, x, y){
  for (const m of cm.extraMarkers) {
    if (Math.hypot(m._x - x, m._y - y) <= m._r + 3) return { kind: 'extra', marker: m };
  }
  for (const m of cm.markers) {
    if (Math.hypot(m.x - x, m.y - y) <= m.r + 3) return { kind: 'place', marker: m };
  }
  return null;
}

function attachCityMapEvents(cm){
  cm.canvas.addEventListener('mousemove', (e) => {
    if (!cm.base) return;
    const { x, y } = cmEventPos(cm, e);
    const hit = cmMarkerAt(cm, x, y);
    const nid = hit ? null : cmNid(cm, Math.floor(y / CITY_SCALE), Math.floor(x / CITY_SCALE));
    cm.canvas.style.cursor = (hit || nid) ? 'pointer' : 'default';
    if (nid !== cm.hoverNid) {
      cm.hoverNid = nid;
      drawCityMap(cm);
    }
  });

  cm.canvas.addEventListener('mouseleave', () => {
    if (!cm.base) return;
    if (cm.hoverNid !== null) { cm.hoverNid = null; drawCityMap(cm); }
  });

  cm.canvas.addEventListener('click', (e) => {
    if (!cm.base) return;
    const { x, y } = cmEventPos(cm, e);
    const hit = cmMarkerAt(cm, x, y);
    if (hit && hit.kind === 'extra') { if (hit.marker.onClick) hit.marker.onClick(); return; }
    if (hit && hit.kind === 'place') { if (cm.onPlaceClick) cm.onPlaceClick(cm, hit.marker); return; }
    const nid = cmNid(cm, Math.floor(y / CITY_SCALE), Math.floor(x / CITY_SCALE));
    if (nid && cm.onNeighborhoodClick) cm.onNeighborhoodClick(cm, nid);
  });
}

// ======================================================================
// Place / neighborhood detail modals -- opened from a map click (either
// tab) via cm.onPlaceClick/cm.onNeighborhoodClick, or from the History
// tab's neighborhood-key/place-card rows. Read hState.data (declared in
// history.js, but -- like everything else here -- only touched at call
// time, well after that script has run).
// ======================================================================

function openNeighborhoodModal(cm, nid){
  const hood = cm.hoodById[nid];
  const data = hState.data;
  if (!hood || !data) return;
  const era = data.eras.find(er => er.id === hood.era_id);
  const placesById = new Map(data.places.map(p => [p.id, p]));
  const hoodPlaces = (hood.place_ids || []).map(pid => placesById.get(pid)).filter(Boolean);
  const eventCount = hoodPlaces.reduce((sum, p) => sum + p.history.length, 0);
  const figures = data.figures.filter(f => f.era_id === hood.era_id);

  const placeRows = hoodPlaces.map(p => {
    const num = cm.numberByPlaceId[p.id];
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

  openModal(`
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
  `, { wide: true });

  modalBodyEl.querySelector('[data-close]').addEventListener('click', closeModal);
  modalBodyEl.querySelectorAll('[data-place]').forEach(el => {
    el.addEventListener('click', () => openPlaceModal(cm, el.dataset.place, nid));
  });
}

const PLACE_MEDIA_TAGS = ['exterior', 'interior'];

function placeMediaBoxHtml(entityId, tag){
  const item = latestTaggedMedia(entityId, tag);
  const label = tag[0].toUpperCase() + tag.slice(1);
  const frame = item
    ? `<div class="box-frame has-media" data-lightbox="${escapeHtml(item.url)}">${
        item.kind === 'video'
          ? `<video src="${fileUrl(item.url)}" muted loop playsinline></video>`
          : `<img src="${fileUrl(item.url)}" alt="${escapeHtml(item.prompt)}" />`
      }</div>`
    : `<div class="box-frame"><span class="box-empty">No ${label.toLowerCase()} shot yet</span></div>`;
  return `<div class="place-media-box"><div class="box-label">${escapeHtml(label)}</div>${frame}</div>`;
}

function refreshPlaceMediaBoxes(placeId){
  const wrap = document.getElementById('placeMediaBoxes');
  if (!wrap || wrap.dataset.placeId !== placeId) return;
  wrap.innerHTML = PLACE_MEDIA_TAGS.map(t => placeMediaBoxHtml(placeId, t)).join('');
}

document.addEventListener('entity-media-refreshed', (e) => refreshPlaceMediaBoxes(e.detail.entityId));

document.addEventListener('click', (e) => {
  const frame = e.target.closest('.box-frame.has-media');
  if (!frame) return;
  const url = frame.dataset.lightbox;
  const isVideo = !!frame.querySelector('video');
  openModal(isVideo
    ? `<video src="${fileUrl(url)}" controls autoplay style="display:block;max-width:100%;"></video>`
    : `<img src="${fileUrl(url)}" style="display:block;max-width:100%;" />`, { wide: true });
});

function openPlaceModal(cm, placeId, fromNid){
  const data = hState.data;
  if (!data) return;
  const place = data.places.find(p => p.id === placeId);
  if (!place) return;
  const figuresById = new Map(data.figures.map(f => [f.id, f]));
  const founder = figuresById.get(place.founding_figure_id);
  const owner = figuresById.get(place.current_owner_figure_id);
  const num = cm.numberByPlaceId[placeId];
  const statusText = place.status === 'active'
    ? 'still active'
    : `${place.status}${place.closed_year ? ' ' + place.closed_year : ''}`;

  const timeline = place.history.map(h =>
    `<div class="modal-event"><span class="year">${h.year}</span>${escapeHtml(h.gospel_text)}</div>`
  ).join('') || '<div class="modal-empty">No recorded events.</div>';

  openModal(`
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
    <div class="place-media-boxes" id="placeMediaBoxes" data-place-id="${escapeHtml(place.id)}">
      ${PLACE_MEDIA_TAGS.map(t => placeMediaBoxHtml(place.id, t)).join('')}
    </div>
    <div class="modal-body-pad">${entityMediaHtml(place.id, 'place', `Describe a photo of ${place.name}…`, PLACE_MEDIA_TAGS)}</div>
    <div class="modal-section-label">History</div>
    ${timeline}
  `, { wide: true });

  modalBodyEl.querySelector('[data-close]').addEventListener('click', closeModal);
  const back = modalBodyEl.querySelector('[data-back]');
  if (back) back.addEventListener('click', () => openNeighborhoodModal(cm, fromNid));
}
