import { useCallback, useEffect, useRef, useState } from 'react';
import { history } from '../api/client';
import type { CitySummary } from '../api/types';
import { NewCityModal } from './NewCityModal';
import { navigate } from './router';
import { useJobStore } from '../state/jobStore';
import './cities.css';

// A plain grid, not a React Flow canvas -- unlike every other screen in
// this app, there's no real graph here (no edges, nothing to wire
// between cities), so a canvas would just be pretending. City nodes here
// are index tiles: pick one to open, generate a new one, or delete one.
export function CitiesScreen() {
  const [cities, setCities] = useState<CitySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newCityModalOpen, setNewCityModalOpen] = useState(false);
  const historyStatus = useJobStore((s) => s.historyStatus);

  const load = useCallback(() => {
    history.listCities().then((res) => setCities(res.cities)).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(load, [load]);

  const prevPhase = useRef(historyStatus?.phase);
  useEffect(() => {
    if (prevPhase.current === 'running' && historyStatus?.phase === 'done') load();
    prevPhase.current = historyStatus?.phase;
  }, [historyStatus?.phase, load]);

  async function removeCity(cityId: string) {
    try {
      const res = await history.deleteCityById(cityId);
      if (!res.ok) setError(res.error ?? 'failed to delete');
      else load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const generating = historyStatus?.phase === 'running';

  if (cities === null) return <div className="canvas-empty">Loading…</div>;

  return (
    <div className="cities-screen">
      <div className="cities-toolbar">
        <button
          className="node-run-btn"
          style={{ flex: 'none', padding: '8px 16px' }}
          disabled={generating}
          onClick={() => setNewCityModalOpen(true)}
        >
          {generating ? 'generating…' : '+ New City'}
        </button>
        {error && <span className="node-error-text">{error}</span>}
      </div>

      {newCityModalOpen && (
        <NewCityModal
          onClose={() => setNewCityModalOpen(false)}
          onStarted={() => setNewCityModalOpen(false)}
        />
      )}

      {cities.length === 0 ? (
        <div className="canvas-empty">No cities yet -- hit "+ New City" to generate one.</div>
      ) : (
        <div className="cities-grid">
          {cities.map((c) => (
            <div key={c.id} className={`city-card ${c.is_active ? 'is-active' : ''}`}>
              <div className="city-card-header">
                <span className="city-card-id">{c.id}</span>
                {c.is_active && <span className="city-card-active">● active</span>}
              </div>
              <p className="city-card-summary">{c.summary || 'No summary yet.'}</p>
              <div className="city-card-stats">
                <span>{c.figure_count} figures</span>
                <span>{c.place_count} places</span>
                <span>{c.character_count} residents</span>
              </div>
              <div className="city-card-actions">
                <button className="node-run-btn" onClick={() => navigate({ kind: 'city', cityId: c.id })}>
                  open
                </button>
                <button
                  className="node-run-btn node-delete-btn"
                  onClick={() =>
                    window.confirm(`Permanently delete "${c.id}"? This removes every figure, place, agent, and generated media in it -- there is no undo.`) &&
                    removeCity(c.id)
                  }
                >
                  delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
