// A config step in front of "+ New City" -- history/routes.py's POST
// /generate already accepts seed/figures_per_era/events_per_figure/
// no_llm (see run_history() in history/generate.py), CitiesScreen just
// never exposed them, always calling generate({}). No preview step here
// (unlike NewAgentModal's character draft) -- generation is an async job,
// not something to preview synchronously, so this is a single-step form:
// pick options, kick off the job, close. Reuses NewAgentModal's own
// generic `.modal-*` CSS rather than duplicating it.
import { useEffect, useRef, useState } from 'react';
import { history, themesApi } from '../api/client';
import type { ThemeSummary } from '../api/types';
import '../flow/newAgentModal.css';

export function NewCityModal({ onStarted, onClose }: { onStarted: () => void; onClose: () => void }) {
  const [seed, setSeed] = useState('');
  const [figuresPerEra, setFiguresPerEra] = useState('');
  const [eventsPerFigure, setEventsPerFigure] = useState('');
  const [useLlm, setUseLlm] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [themes, setThemes] = useState<ThemeSummary[]>([]);
  const [themeId, setThemeId] = useState('');
  const [problems, setProblems] = useState<string[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  async function loadThemes(select?: string) {
    const res = await themesApi.list();
    setThemes(res.themes);
    setThemeId((current) => select ?? (current || res.default));
  }

  useEffect(() => {
    themesApi
      .list()
      .then((res) => {
        setThemes(res.themes);
        setThemeId((current) => current || res.default);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function uploadTheme(file: File) {
    setUploading(true);
    setProblems([]);
    setError(null);
    try {
      const res = await themesApi.upload(await file.text());
      if (res.ok && res.theme) await loadThemes(res.theme.id);
      else setProblems(res.problems ?? ['upload failed']);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = '';
    }
  }

  async function removeTheme() {
    if (!window.confirm(`Remove the uploaded theme "${selected?.name}"? Cities already made with it keep their own copy.`)) return;
    await themesApi.remove(themeId);
    setThemeId('');
    await loadThemes();
  }

  const selected = themes.find((t) => t.id === themeId);

  async function start() {
    setPending(true);
    setError(null);
    try {
      const res = await history.generate({
        seed: seed.trim() ? Number(seed) : undefined,
        figuresPerEra: figuresPerEra.trim() ? Number(figuresPerEra) : undefined,
        eventsPerFigure: eventsPerFigure.trim() ? Number(eventsPerFigure) : undefined,
        noLlm: !useLlm,
        themeId: themeId || undefined,
      });
      if (!res.ok) {
        setError(res.error ?? 'failed to start');
        return;
      }
      onStarted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>New City</h3>
          <button className="modal-close" title="Close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="modal-body">
          <label className="modal-field">
            <span>Theme</span>
            <select value={themeId} onChange={(e) => setThemeId(e.target.value)}>
              {themes.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                  {t.source === 'uploaded' ? ' (uploaded)' : ''}
                </option>
              ))}
            </select>
          </label>
          {selected && (
            <div className="modal-hint">
              {selected.description}
              <div className="modal-theme-actions">
                <a href={themesApi.fileUrl(selected.id)} download>
                  download this theme
                </a>
                <span> · </span>
                <button type="button" className="modal-link" disabled={uploading} onClick={() => fileInput.current?.click()}>
                  {uploading ? 'checking…' : 'upload a theme…'}
                </button>
                {selected.source === 'uploaded' && (
                  <>
                    <span> · </span>
                    <button type="button" className="modal-link" onClick={removeTheme}>
                      remove
                    </button>
                  </>
                )}
              </div>
              <input
                ref={fileInput}
                type="file"
                accept=".yaml,.yml,application/x-yaml,text/yaml"
                style={{ display: 'none' }}
                onChange={(e) => e.target.files?.[0] && uploadTheme(e.target.files[0])}
              />
            </div>
          )}
          {problems.length > 0 && (
            <div className="modal-error">
              That theme can&rsquo;t be used yet:
              <ul className="modal-problems">
                {problems.map((p, i) => (
                  <li key={i}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          <label className="modal-field">
            <span>Seed (optional)</span>
            <input type="number" placeholder="random" value={seed} onChange={(e) => setSeed(e.target.value)} />
          </label>
          <div className="modal-field-row">
            <label className="modal-field">
              <span>Figures per era</span>
              <input
                type="number"
                min={1}
                placeholder="default"
                value={figuresPerEra}
                onChange={(e) => setFiguresPerEra(e.target.value)}
              />
            </label>
            <label className="modal-field">
              <span>Events per figure</span>
              <input
                type="number"
                min={1}
                placeholder="default"
                value={eventsPerFigure}
                onChange={(e) => setEventsPerFigure(e.target.value)}
              />
            </label>
          </div>
          <label className="modal-field modal-checkbox-field">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            <span>Use LLM to fill in names/flourish text</span>
          </label>
          <div className="modal-hint">
            The theme sets the world: its eras, names, places, events and every prompt. To make your own, download a
            theme, edit it, and upload it. These numbers only control how much gets generated. Residents aren't part
            of city generation -- add them afterward from the city's own canvas.
          </div>
          {error && <div className="modal-error">{error}</div>}
        </div>
        <div className="modal-actions">
          <button className="node-run-btn" onClick={onClose}>
            Cancel
          </button>
          <button className="node-run-btn" disabled={pending} onClick={start}>
            {pending ? 'starting…' : '▶ Generate'}
          </button>
        </div>
      </div>
    </div>
  );
}
