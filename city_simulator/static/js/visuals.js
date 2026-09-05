"use strict";

// ======================================================================
// Visuals tab
// ======================================================================

const vState = {
  gallery: [],             // {kind: "image"|"video", url, prompt} newest-first
  editImagePath: null,     // server-side path of the uploaded "starting image" for Generate Image
  videoSourcePath: null,   // server-side path of the source image for Generate Video
  lastPhase: null,
};

const visualsStatusPill = document.getElementById('visualsStatusPill');
const visualsStatusText = document.getElementById('visualsStatusText');
const visualsErrorMsg = document.getElementById('visualsErrorMsg');
const generateImageBtn = document.getElementById('generateImageBtn');
const generateVideoBtn = document.getElementById('generateVideoBtn');

function fileUrl(relativeUrl){
  return '/api/visuals/files/' + relativeUrl;
}

function uploadImage(file){
  const formData = new FormData();
  formData.append('image', file);
  return fetch('/api/visuals/upload', { method: 'POST', body: formData }).then(r => r.json());
}

// --- starting image for Generate Image (optional -- edit vs. from scratch) ---

document.getElementById('imageFileInput').addEventListener('change', (e) => {
  const file = e.target.files[0];
  const preview = document.getElementById('imageFilePreview');
  if (!file) {
    vState.editImagePath = null;
    preview.style.display = 'none';
    return;
  }
  preview.style.display = '';
  preview.innerHTML = `<img src="${URL.createObjectURL(file)}" alt="starting image preview" />`;
  uploadImage(file).then(d => {
    if (d.ok) vState.editImagePath = d.path;
    else visualsErrorMsg.textContent = d.error || 'upload failed';
  });
});

// --- source image for Generate Video ---

function setVideoSource(path, previewHtml){
  vState.videoSourcePath = path;
  document.getElementById('videoSourcePreview').innerHTML = previewHtml;
  generateVideoBtn.disabled = false;
}

document.getElementById('videoFileInput').addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const localPreview = URL.createObjectURL(file);
  uploadImage(file).then(d => {
    if (d.ok) setVideoSource(d.path, `<img src="${localPreview}" alt="video source preview" />`);
    else visualsErrorMsg.textContent = d.error || 'upload failed';
  });
});

// --- gallery ---

function galleryCardHtml(item, index){
  const media = item.kind === 'video'
    ? `<video src="${fileUrl(item.url)}" controls></video>`
    : `<img src="${fileUrl(item.url)}" alt="${escapeHtml(item.prompt)}" />`;
  const animateBtn = item.kind === 'image'
    ? `<button data-animate="${index}">Animate this</button>` : '';
  return `
    <div class="visuals-card">
      ${media}
      <div class="body">
        <div class="kind">${item.kind}</div>
        <div class="prompt">${escapeHtml(item.prompt)}</div>
        <div class="actions">${animateBtn}</div>
      </div>
    </div>
  `;
}

function renderGallery(){
  document.getElementById('visualsEmpty').style.display = vState.gallery.length ? 'none' : '';
  const galleryEl = document.getElementById('visualsGallery');
  galleryEl.innerHTML = vState.gallery.map(galleryCardHtml).join('');
  galleryEl.querySelectorAll('[data-animate]').forEach(btn => {
    btn.addEventListener('click', () => {
      const item = vState.gallery[parseInt(btn.dataset.animate, 10)];
      setVideoSource(item.localPath, `<img src="${fileUrl(item.url)}" alt="video source preview" />`);
    });
  });
}

// --- generation ---

function pollVisualsStatus(){
  fetch('/api/visuals/status').then(r => r.json()).then(d => {
    const phase = d.phase || 'idle';
    visualsStatusPill.className = 'status-pill ' + phase;
    visualsStatusText.textContent = phase;
    visualsErrorMsg.textContent = d.error || '';
    generateImageBtn.disabled = phase === 'running';
    generateVideoBtn.disabled = (phase === 'running') || !vState.videoSourcePath;

    if (phase === 'done' && vState.lastPhase !== 'done') {
      fetch('/api/visuals/result').then(r => r.json()).then(result => {
        if (result.kind === 'image') {
          result.images.forEach(img => {
            vState.gallery.unshift({ kind: 'image', url: img.url, localPath: img.local_path, prompt: vState.lastImagePrompt || '' });
          });
        } else if (result.kind === 'video') {
          vState.gallery.unshift({ kind: 'video', url: result.video.url, localPath: result.video.local_path, prompt: vState.lastVideoPrompt || '' });
        }
        renderGallery();
      });
    }
    vState.lastPhase = phase;
  }).catch(() => {});
}

setInterval(pollVisualsStatus, 1200);
pollVisualsStatus();

generateImageBtn.addEventListener('click', () => {
  const prompt = document.getElementById('imagePromptInput').value.trim();
  if (!prompt) { visualsErrorMsg.textContent = 'enter a prompt first'; return; }
  const payload = {
    prompt,
    image_paths: vState.editImagePath ? [vState.editImagePath] : null,
    options: {
      aspect_ratio: document.getElementById('imageAspectInput').value,
      resolution: document.getElementById('imageResolutionInput').value,
    },
  };
  fetch('/api/visuals/generate-image', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }).then(r => r.json()).then(d => {
    if (!d.ok) { visualsErrorMsg.textContent = d.error || 'could not start generation'; return; }
    vState.lastImagePrompt = prompt;
    pollVisualsStatus();
  });
});

generateVideoBtn.addEventListener('click', () => {
  const prompt = document.getElementById('videoPromptInput').value.trim();
  if (!prompt) { visualsErrorMsg.textContent = 'enter an animation prompt first'; return; }
  if (!vState.videoSourcePath) { visualsErrorMsg.textContent = 'pick a source image first'; return; }
  const payload = {
    prompt,
    image_path: vState.videoSourcePath,
    options: {
      aspect_ratio: document.getElementById('videoAspectInput').value,
      resolution: document.getElementById('videoResolutionInput').value,
      duration: parseInt(document.getElementById('videoDurationInput').value, 10) || 8,
    },
  };
  fetch('/api/visuals/generate-video', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }).then(r => r.json()).then(d => {
    if (!d.ok) { visualsErrorMsg.textContent = d.error || 'could not start generation'; return; }
    vState.lastVideoPrompt = prompt;
    pollVisualsStatus();
  });
});
