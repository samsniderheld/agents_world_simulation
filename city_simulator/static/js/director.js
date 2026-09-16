"use strict";

// ======================================================================
// Director tab -- pick an existing character, generate/reuse one of
// their treatments, then generate storyboard shot images and a separate
// "character map" (the character-sheet turnaround, prompt fully
// editable here, unlike the agent modal's auto-appended version).
//
// Reuses the existing image-generation pipeline (POST /api/visuals/
// generate-image -> poll /status -> /result -> POST /api/city/media,
// see main.js's startEntityMediaGeneration/pollEntityMediaJob for the
// reference shape) but with its own poll loop rather than reusing those
// functions directly -- they're tightly coupled to entityMediaHtml()'s
// compact-widget markup and refreshEntityMediaDom()'s rebuild, neither
// of which know about this tab's card layout.
// ======================================================================

const dState = {
  characterId: null,
  characterRecord: null,  // full GET /api/city/agents/<id> response
  treatments: [],
  generating: false,       // visuals/jobs.py has one global job slot --
                            // this mirrors that constraint tab-wide, since
                            // up to 7 Generate buttons are on screen at once
};

function directorResultHtml(item){
  if (!item) return '<div class="director-result-empty">Not generated yet.</div>';
  const url = cityFileUrl(item.url);
  const filename = item.url.split('/').pop();
  return `
    <div class="director-result-media">
      <img src="${url}" alt="${escapeHtml(item.prompt)}" data-lightbox="${escapeHtml(item.url)}" />
      <a class="director-download" href="${url}" download="${escapeHtml(filename)}">⬇ Download</a>
    </div>
  `;
}

function renderDirectorResult(tag, el){
  if (!el || !dState.characterId) return;
  el.innerHTML = directorResultHtml(latestTaggedMedia(dState.characterId, tag));
}

function setDirectorButtonsDisabled(disabled){
  document.querySelectorAll('#directorContent button').forEach(b => b.disabled = disabled);
}

// --- generation (shared by every Generate button in this tab) ----------

function pollDirectorImageJob(entityId, tag, prompt, statusEl, resultEl){
  fetch('/api/visuals/status').then(r => r.json()).then(d => {
    const phase = d.phase || 'idle';
    if (phase === 'running') {
      setTimeout(() => pollDirectorImageJob(entityId, tag, prompt, statusEl, resultEl), 1500);
      return;
    }
    dState.generating = false;
    setDirectorButtonsDisabled(false);
    if (phase === 'error') { if (statusEl) statusEl.textContent = d.error || 'generation failed'; return; }
    if (phase !== 'done') { if (statusEl) statusEl.textContent = ''; return; }
    fetch('/api/visuals/result').then(r => r.json()).then(result => {
      const media = (result.kind === 'image' && result.images && result.images.length) ? result.images[0] : null;
      if (!media) { if (statusEl) statusEl.textContent = 'unexpected result from the generator'; return; }
      fetch('/api/city/media', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entity_id: entityId, kind: 'image', url: media.url, local_path: media.local_path, prompt, tag }),
      }).then(r => r.json()).then(cityRes => {
        if (!cityRes.ok) { if (statusEl) statusEl.textContent = cityRes.error || 'could not attach media'; return; }
        if (!hState.data.media) hState.data.media = {};
        hState.data.media[entityId] = cityRes.media;
        if (statusEl) statusEl.textContent = '';
        if (resultEl) resultEl.innerHTML = directorResultHtml(latestTaggedMedia(entityId, tag));
      });
    });
  }).catch(() => {
    dState.generating = false;
    setDirectorButtonsDisabled(false);
    if (statusEl) statusEl.textContent = 'lost contact with the server';
  });
}

function generateDirectorImage(entityId, tag, prompt, statusEl, resultEl){
  if (!entityId) return;
  if (!prompt) { if (statusEl) statusEl.textContent = 'enter a prompt first'; return; }
  if (dState.generating) { if (statusEl) statusEl.textContent = 'another generation is already running'; return; }
  dState.generating = true;
  setDirectorButtonsDisabled(true);
  if (statusEl) statusEl.textContent = 'starting…';

  fetch('/api/visuals/generate-image', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, image_paths: null, options: { aspect_ratio: '16:9' } }),
  }).then(r => r.json()).then(d => {
    if (!d.ok) {
      dState.generating = false;
      setDirectorButtonsDisabled(false);
      if (statusEl) statusEl.textContent = d.error || 'could not start generation';
      return;
    }
    if (statusEl) statusEl.textContent = 'generating (this can take a minute)…';
    pollDirectorImageJob(entityId, tag, prompt, statusEl, resultEl);
  });
}

// --- storyboard ----------------------------------------------------------

function storyboardShotHtml(num, promptText){
  return `
    <div class="storyboard-shot">
      <div class="shot-label">Shot ${num}</div>
      <textarea class="shot-prompt-input" id="directorShotPrompt${num}" rows="4">${escapeHtml(promptText)}</textarea>
      <div class="modal-actions" style="justify-content:flex-start; padding:8px 0 0;">
        <button data-shot="${num}" data-action="director-gen-shot">Generate</button>
        <span class="media-status" id="directorShotStatus${num}"></span>
      </div>
      <div class="director-result" id="directorShotResult${num}"></div>
    </div>
  `;
}

function loadDirectorShots(text){
  const section = document.getElementById('directorStoryboardSection');
  const grid = document.getElementById('directorStoryboardGrid');
  fetch(`/api/agents/treatment/shots?text=${encodeURIComponent(text)}`).then(r => r.json()).then(d => {
    const shots = d.shots || [];
    if (!shots.length) { section.style.display = 'none'; grid.innerHTML = ''; return; }
    section.style.display = '';
    grid.innerHTML = shots.map((shot, i) => storyboardShotHtml(i + 1, shot)).join('');
    shots.forEach((_, i) => {
      const num = i + 1;
      renderDirectorResult(`storyboard_${num}`, document.getElementById(`directorShotResult${num}`));
    });
  });
}

// --- treatment -------------------------------------------------------------

function selectDirectorTreatment(index){
  const treatment = dState.treatments[index];
  const textEl = document.getElementById('directorTreatmentText');
  const storyboardSection = document.getElementById('directorStoryboardSection');
  if (!treatment) {
    textEl.textContent = '';
    storyboardSection.style.display = 'none';
    return;
  }
  textEl.textContent = treatment.text;
  loadDirectorShots(treatment.text);
}

function populateDirectorTreatments(){
  const select = document.getElementById('directorTreatmentInput');
  const treatments = (dState.characterRecord && dState.characterRecord.treatments) || [];
  dState.treatments = treatments;
  select.innerHTML = treatments.length
    ? treatments.map((t, i) => `<option value="${i}">${escapeHtml(t.created_at ? new Date(t.created_at).toLocaleString() : `Treatment ${i + 1}`)}</option>`).join('')
    : '<option value="">No treatments yet</option>';
  const defaultIndex = treatments.length - 1;
  select.value = String(defaultIndex);
  selectDirectorTreatment(defaultIndex);
}

// --- character ---------------------------------------------------------

function loadDirectorCharacter(characterId){
  dState.characterId = characterId || null;
  dState.characterRecord = null;
  dState.treatments = [];
  if (!characterId) {
    populateDirectorTreatments();
    return;
  }
  fetch(`/api/city/agents/${encodeURIComponent(characterId)}`).then(r => r.ok ? r.json() : null).then(record => {
    dState.characterRecord = record;
    populateDirectorTreatments();

    const character = (hState.data.characters || []).find(c => c.id === characterId);
    const promptEl = document.getElementById('directorCharacterMapPrompt');
    if (promptEl && character) {
      let text = character.name;
      if (character.bio) text += `. ${character.bio}`;
      promptEl.value = `${text}\n\n${CHARACTER_SHEET_STYLE}`;
    }
    renderDirectorResult('character_map', document.getElementById('directorCharacterMapResult'));
  });
}

function populateDirectorCharacters(){
  const select = document.getElementById('directorCharacterInput');
  const chars = (hState.data && hState.data.characters) || [];
  const previous = dState.characterId;
  select.innerHTML = chars.map(c =>
    `<option value="${escapeHtml(c.id)}">${escapeHtml(c.name)} (${escapeHtml(c.occupation || '')})</option>`
  ).join('');
  const stillValid = previous && chars.some(c => c.id === previous);
  select.value = stillValid ? previous : (chars[0] ? chars[0].id : '');
}

function refreshDirectorTab(){
  const chars = (hState.data && hState.data.characters) || [];
  document.getElementById('directorEmpty').style.display = chars.length ? 'none' : '';
  document.getElementById('directorContent').style.display = chars.length ? '' : 'none';
  if (!chars.length) return;
  populateDirectorCharacters();
  loadDirectorCharacter(document.getElementById('directorCharacterInput').value);
}

// --- wiring --------------------------------------------------------------

document.getElementById('directorCharacterInput').addEventListener('change', (e) => {
  loadDirectorCharacter(e.target.value);
});

document.getElementById('directorTreatmentInput').addEventListener('change', (e) => {
  selectDirectorTreatment(parseInt(e.target.value, 10));
});

document.getElementById('directorGenerateTreatmentBtn').addEventListener('click', () => {
  const statusEl = document.getElementById('directorTreatmentStatus');
  const btn = document.getElementById('directorGenerateTreatmentBtn');
  if (!dState.characterId) return;
  btn.disabled = true;
  statusEl.textContent = 'generating…';
  fetch('/api/agents/treatment', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agent_id: dState.characterId }),
  }).then(r => r.json()).then(d => {
    btn.disabled = false;
    if (!d.treatment) { statusEl.textContent = d.error || 'could not generate a treatment'; return; }
    statusEl.textContent = '';
    loadDirectorCharacter(dState.characterId);
  });
});

document.addEventListener('click', (e) => {
  const shotBtn = e.target.closest('[data-action="director-gen-shot"]');
  if (shotBtn) {
    const num = shotBtn.dataset.shot;
    const promptInput = document.getElementById(`directorShotPrompt${num}`);
    generateDirectorImage(
      dState.characterId, `storyboard_${num}`, promptInput.value.trim(),
      document.getElementById(`directorShotStatus${num}`), document.getElementById(`directorShotResult${num}`),
    );
    return;
  }
  const mapBtn = e.target.closest('[data-action="director-gen-character-map"]');
  if (mapBtn) {
    const promptInput = document.getElementById('directorCharacterMapPrompt');
    generateDirectorImage(
      dState.characterId, 'character_map', promptInput.value.trim(),
      document.getElementById('directorCharacterMapStatus'), document.getElementById('directorCharacterMapResult'),
    );
  }
});

const directorTabBtn = document.querySelector('.tab-btn[data-tab="director"]');
if (directorTabBtn) directorTabBtn.addEventListener('click', refreshDirectorTab);
