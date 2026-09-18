"use strict";

// Studio tab -- ad-hoc image and music generation with no place/agent/
// character attached, for whenever you just want to prompt something.
// There's no entity id to hang a citystate.store.add_media() call on, so
// results aren't persisted anywhere -- just kept in plain in-memory
// arrays for the current page session (newest first), with a download
// link on each card for anything worth keeping. The generated file
// itself still lands on disk via visuals/storage.py; only the
// "attached to something" bookkeeping is skipped.
//
// Image and music generation share visuals/jobs.py's single global job
// slot (same as every other tab), so studioGenerating/setStudioBusy locks
// both of this tab's Generate buttons together, not just the one in use.

let studioGenerating = false;
const studioGallery = [];
const studioMusicGallery = [];

// Reference images for image-to-image/edit generation -- each is uploaded
// to disk immediately on selection (POST /api/visuals/upload) so its local
// path is ready to hand straight to generate-image's image_paths, which
// (per fal.py's generate_image) switches fal to its edit model and reads
// each path straight off disk. {path, url, name} per entry; kept across
// generations so the same references can be reused for a follow-up prompt.
const studioReferenceImages = [];

function setStudioBusy(busy){
  studioGenerating = busy;
  document.getElementById('studioGenerateBtn').disabled = busy;
  document.getElementById('studioMusicGenerateBtn').disabled = busy;
}

function pollStudioJob(statusEl, onResult){
  fetch('/api/visuals/status').then(r => r.json()).then(d => {
    const phase = d.phase || 'idle';
    if (phase === 'running') { setTimeout(() => pollStudioJob(statusEl, onResult), 1500); return; }
    setStudioBusy(false);
    if (phase === 'error') { statusEl.textContent = d.error || 'generation failed'; return; }
    if (phase !== 'done') { statusEl.textContent = ''; return; }
    fetch('/api/visuals/result').then(r => r.json()).then(onResult);
  }).catch(() => {
    setStudioBusy(false);
    statusEl.textContent = 'lost contact with the server';
  });
}

// --- images --------------------------------------------------------------

function studioCardHtml(entry){
  const url = visualsFileUrl(entry.url);
  const filename = entry.url.split('/').pop();
  return `
    <div class="studio-card">
      <img src="${url}" alt="${escapeHtml(entry.prompt)}" data-lightbox="${escapeHtml(entry.url)}" />
      <div class="studio-card-prompt">${escapeHtml(entry.prompt)}</div>
      <a class="studio-download" href="${url}" download="${escapeHtml(filename)}">⬇ Download</a>
    </div>
  `;
}

function renderStudioGallery(){
  const grid = document.getElementById('studioGallery');
  const empty = document.getElementById('studioGalleryEmpty');
  empty.style.display = studioGallery.length ? 'none' : '';
  grid.innerHTML = studioGallery.map(studioCardHtml).join('');
}

function studioRefThumbHtml(ref, index){
  return `
    <div class="studio-ref-thumb">
      <img src="${visualsFileUrl(ref.url)}" alt="${escapeHtml(ref.name)}" />
      <button class="studio-ref-remove" data-ref-index="${index}" title="Remove">×</button>
    </div>
  `;
}

function renderStudioRefs(){
  document.getElementById('studioRefsList').innerHTML = studioReferenceImages.map(studioRefThumbHtml).join('');
}

function uploadStudioReference(file){
  const formData = new FormData();
  formData.append('file', file);
  return fetch('/api/visuals/upload', { method: 'POST', body: formData }).then(r => r.json()).then(d => {
    if (!d.ok) throw new Error(d.error || `could not upload ${file.name}`);
    studioReferenceImages.push({ path: d.path, url: d.url, name: file.name });
  });
}

document.getElementById('studioRefInput').addEventListener('change', (e) => {
  const files = Array.from(e.target.files || []);
  if (!files.length) return;
  const statusEl = document.getElementById('studioStatus');
  statusEl.textContent = `uploading ${files.length} reference image${files.length === 1 ? '' : 's'}…`;
  Promise.all(files.map(uploadStudioReference)).then(() => {
    statusEl.textContent = '';
  }).catch(err => {
    statusEl.textContent = err.message || 'could not upload reference image';
  }).finally(() => {
    renderStudioRefs();
    e.target.value = '';
  });
});

document.getElementById('studioRefsList').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-ref-index]');
  if (!btn) return;
  studioReferenceImages.splice(Number(btn.dataset.refIndex), 1);
  renderStudioRefs();
});

document.getElementById('studioGenerateBtn').addEventListener('click', () => {
  const promptEl = document.getElementById('studioPrompt');
  const statusEl = document.getElementById('studioStatus');
  const prompt = promptEl.value.trim();
  if (!prompt) { statusEl.textContent = 'enter a description first'; return; }
  if (studioGenerating) { statusEl.textContent = 'a generation is already running'; return; }
  setStudioBusy(true);
  statusEl.textContent = 'starting…';

  const imagePaths = studioReferenceImages.length ? studioReferenceImages.map(r => r.path) : null;
  fetch('/api/visuals/generate-image', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, image_paths: imagePaths, options: { aspect_ratio: '16:9' } }),
  }).then(r => r.json()).then(d => {
    if (!d.ok) {
      setStudioBusy(false);
      statusEl.textContent = d.error || 'could not start generation';
      return;
    }
    statusEl.textContent = 'generating (this can take a minute)…';
    pollStudioJob(statusEl, (result) => {
      const media = (result.kind === 'image' && result.images && result.images.length) ? result.images[0] : null;
      if (!media) { statusEl.textContent = 'unexpected result from the generator'; return; }
      statusEl.textContent = '';
      studioGallery.unshift({ prompt, url: media.url });
      renderStudioGallery();
    });
  });
});

// --- music -----------------------------------------------------------------

function studioMusicCardHtml(entry){
  const url = visualsFileUrl(entry.url);
  const filename = entry.url.split('/').pop();
  return `
    <div class="studio-card">
      <audio src="${url}" controls></audio>
      <div class="studio-card-prompt">${escapeHtml(entry.prompt)}</div>
      <a class="studio-download" href="${url}" download="${escapeHtml(filename)}">⬇ Download</a>
    </div>
  `;
}

function renderStudioMusicGallery(){
  const grid = document.getElementById('studioMusicGallery');
  const empty = document.getElementById('studioMusicGalleryEmpty');
  empty.style.display = studioMusicGallery.length ? 'none' : '';
  grid.innerHTML = studioMusicGallery.map(studioMusicCardHtml).join('');
}

document.getElementById('studioMusicGenerateBtn').addEventListener('click', () => {
  const promptEl = document.getElementById('studioMusicPrompt');
  const negativeEl = document.getElementById('studioMusicNegative');
  const statusEl = document.getElementById('studioMusicStatus');
  const prompt = promptEl.value.trim();
  if (!prompt) { statusEl.textContent = 'enter a description first'; return; }
  if (studioGenerating) { statusEl.textContent = 'a generation is already running'; return; }
  setStudioBusy(true);
  statusEl.textContent = 'starting…';

  const options = {};
  const negative = negativeEl.value.trim();
  if (negative) options.negative_prompt = negative;

  fetch('/api/visuals/generate-music', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, options }),
  }).then(r => r.json()).then(d => {
    if (!d.ok) {
      setStudioBusy(false);
      statusEl.textContent = d.error || 'could not start generation';
      return;
    }
    statusEl.textContent = 'generating (this can take a minute)…';
    pollStudioJob(statusEl, (result) => {
      const audio = result.kind === 'music' ? result.audio : null;
      if (!audio) { statusEl.textContent = 'unexpected result from the generator'; return; }
      statusEl.textContent = '';
      studioMusicGallery.unshift({ prompt, url: audio.url });
      renderStudioMusicGallery();
    });
  });
});
