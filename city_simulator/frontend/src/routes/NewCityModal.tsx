// A config step in front of "+ New City" -- history/routes.py's POST
// /generate already accepts seed/figures_per_era/events_per_figure/
// no_llm (see run_history() in history/generate.py), CitiesScreen just
// never exposed them, always calling generate({}). No preview step here
// (unlike NewAgentModal's character draft) -- generation is an async job,
// not something to preview synchronously, so this is a single-step form:
// pick options, kick off the job, close. Reuses NewAgentModal's own
// generic `.modal-*` CSS rather than duplicating it.
import { useState } from 'react';
import { history } from '../api/client';
import '../flow/newAgentModal.css';

export function NewCityModal({ onStarted, onClose }: { onStarted: () => void; onClose: () => void }) {
  const [seed, setSeed] = useState('');
  const [figuresPerEra, setFiguresPerEra] = useState('');
  const [eventsPerFigure, setEventsPerFigure] = useState('');
  const [useLlm, setUseLlm] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setPending(true);
    setError(null);
    try {
      const res = await history.generate({
        seed: seed.trim() ? Number(seed) : undefined,
        figuresPerEra: figuresPerEra.trim() ? Number(figuresPerEra) : undefined,
        eventsPerFigure: eventsPerFigure.trim() ? Number(eventsPerFigure) : undefined,
        noLlm: !useLlm,
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
            Eras themselves are fixed (a set 1624-1950 timeline); these only control how much gets generated within
            them. Residents aren't part of city generation anymore -- add them afterward from the city's own canvas.
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
