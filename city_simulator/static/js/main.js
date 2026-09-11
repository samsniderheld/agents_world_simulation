"use strict";

function escapeHtml(s){
  return String(s).replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// Entity-attached media (place/agent portraits, exterior/interior shots)
// lives under citystate/data/ -- see citystate/store.py's add_media().
function cityFileUrl(relativeUrl){
  return '/api/city/files/' + relativeUrl;
}

// --- shared modal shell ------------------------------------------------
//
// One overlay for the whole app (settings forms, place/agent detail,
// the history log, image lightboxes) -- every tab calls through this
// instead of keeping its own modal DOM/CSS.

const modalOverlayEl = document.getElementById('modalOverlay');
const modalBodyEl = document.getElementById('modalBody');

function openModal(html, { wide = false } = {}){
  modalBodyEl.innerHTML = html;
  modalBodyEl.classList.toggle('wide', wide);
  modalOverlayEl.style.display = '';
}

function closeModal(){
  modalOverlayEl.style.display = 'none';
  modalBodyEl.innerHTML = '';
}

modalOverlayEl.addEventListener('click', (e) => {
  if (e.target === modalOverlayEl) closeModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeModal();
});

// --- per-entity media (attached images/video, see citystate/store.py) --
//
// Shared here (not history.js) because both the place modal (citymap.js)
// and character/place cards (history.js) need it, and this file loads
// before either. Reads/writes hState.data.media -- hState itself is
// declared later, in history.js, but only ever touched here at call time
// (after the whole page has loaded).

function entityMediaList(entityId){
  return (hState.data && hState.data.media && hState.data.media[entityId]) || [];
}

function latestImagePath(entityId){
  const images = entityMediaList(entityId).filter(m => m.kind === 'image');
  return images.length ? images[images.length - 1].local_path : null;
}

function latestTaggedMedia(entityId, tag){
  const items = entityMediaList(entityId).filter(m => m.tag === tag);
  return items.length ? items[items.length - 1] : null;
}

function entityThumbHtml(item){
  const media = item.kind === 'video'
    ? `<video src="${cityFileUrl(item.url)}" muted loop playsinline></video>`
    : `<img src="${cityFileUrl(item.url)}" alt="${escapeHtml(item.prompt)}" />`;
  return `<div class="entity-thumb">${media}<button class="entity-thumb-remove" data-remove-media="${escapeHtml(item.id)}" title="Remove">×</button></div>`;
}

// Rendered once as part of a card/modal's own HTML, then refreshed in
// place (see refreshEntityMediaDom) after a generation completes.
// `tags`, if given (e.g. ["exterior", "interior"] for a place), adds a
// small tag picker to the generate form so a new image/video can be
// filed under one of those slots -- see citymap.js's place modal for
// where the tagged boxes above this strip read them back out.
function entityMediaHtml(entityId, entityType, promptHint, tags){
  const items = entityMediaList(entityId);
  const hasImage = items.some(m => m.kind === 'image');
  const tagPicker = tags && tags.length
    ? `<select class="media-tag-input">
        <option value="">Untagged</option>
        ${tags.map(t => `<option value="${escapeHtml(t)}">${escapeHtml(t[0].toUpperCase() + t.slice(1))}</option>`).join('')}
      </select>`
    : '';
  return `
    <div class="entity-media" data-entity-id="${escapeHtml(entityId)}" data-entity-type="${entityType}">
      <div class="entity-media-thumbs">
        ${items.map(entityThumbHtml).join('')}
        <button class="entity-media-toggle" data-action="toggle-media-form">+ Media</button>
      </div>
      <div class="entity-media-form" hidden>
        <input type="text" class="media-prompt-input" placeholder="${escapeHtml(promptHint)}" />
        ${tagPicker}
        <div class="media-form-actions">
          <button data-action="gen-image">Generate Image</button>
          <button data-action="gen-video" ${hasImage ? '' : 'disabled title="Add an image first"'}>Animate Latest Image</button>
        </div>
        <span class="media-status"></span>
      </div>
    </div>
  `;
}

// Re-renders every on-page copy of one entity's media strip (a place can
// appear both in its map modal and, in principle, elsewhere) by rebuilding
// each from scratch with the same promptHint/tags it already had.
function refreshEntityMediaDom(entityId){
  document.querySelectorAll(`.entity-media[data-entity-id="${CSS.escape(entityId)}"]`).forEach(wrap => {
    const entityType = wrap.dataset.entityType;
    const promptHint = wrap.querySelector('.media-prompt-input').placeholder;
    const tagSelect = wrap.querySelector('.media-tag-input');
    const tags = tagSelect ? Array.from(tagSelect.options).map(o => o.value).filter(Boolean) : null;
    const temp = document.createElement('div');
    temp.innerHTML = entityMediaHtml(entityId, entityType, promptHint, tags);
    wrap.replaceWith(temp.firstElementChild);
    document.dispatchEvent(new CustomEvent('entity-media-refreshed', { detail: { entityId } }));
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
    const tagSelect = wrap.querySelector('.media-tag-input');
    const tag = tagSelect ? tagSelect.value : '';
    startEntityMediaGeneration(wrap.dataset.entityId, genBtn.dataset.action === 'gen-video' ? 'video' : 'image', prompt, tag, wrap);
  }
});

function startEntityMediaGeneration(entityId, kind, prompt, tag, wrap){
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
    pollEntityMediaJob(entityId, kind, prompt, tag, wrap);
  });
}

function pollEntityMediaJob(entityId, kind, prompt, tag, wrap){
  const statusEl = wrap.querySelector('.media-status');
  fetch('/api/visuals/status').then(r => r.json()).then(d => {
    const phase = d.phase || 'idle';
    if (phase === 'running') { setTimeout(() => pollEntityMediaJob(entityId, kind, prompt, tag, wrap), 1500); return; }
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
        body: JSON.stringify({ entity_id: entityId, kind, url: media.url, local_path: media.local_path, prompt, tag }),
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

// --- tabs -------------------------------------------------------------

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b === btn));
    document.querySelectorAll('.tab-panel').forEach(p => { p.hidden = p.dataset.tabPanel !== tab; });
  });
});
