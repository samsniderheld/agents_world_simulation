import { useCallback, useEffect, useRef, useState } from 'react';
import { history } from '../api/client';
import type { HistoryData } from '../api/types';
import { firstImageUrl } from '../flow/entityNodeKit';
import { useHiddenEntities } from '../flow/useHiddenEntities';
import { useJobStore } from '../state/jobStore';
import { navigate } from './router';
import './gallery.css';

// A plain card grid, not a React Flow canvas -- like CitiesScreen, this
// is an index/browse view, not a graph. Every Agent/Location in the city
// always renders here regardless of its hidden-from-drawer state (see
// useHiddenEntities.ts's own docstring): the toggle only thins each
// canvas's own "+ Agent"/"+ Location" drawer list, never this view.
function NotFoundState() {
  return (
    <div className="canvas-empty">
      <p>This city no longer exists.</p>
      <button className="node-run-btn" style={{ flex: 'none', padding: '8px 16px' }} onClick={() => navigate({ kind: 'root' })}>
        ← back to Cities
      </button>
    </div>
  );
}

export function GalleryScreen({ cityId }: { cityId: string }) {
  const [data, setData] = useState<HistoryData | null | undefined>(undefined);
  const historyStatus = useJobStore((s) => s.historyStatus);
  const { isHidden, toggle } = useHiddenEntities(cityId);

  // Same "activate then read" requirement as CityCanvas/AgentScreen --
  // GET-style reads implicitly operate on whichever city is active
  // server-side, so arriving here directly (a bookmark, a refresh) has
  // to activate cityId first rather than assume it already is.
  const load = useCallback(() => {
    history
      .activateCity(cityId)
      .then((res) => setData(res.city))
      .catch(() => setData(null));
  }, [cityId]);

  useEffect(load, [load]);

  const prevPhase = useRef(historyStatus?.phase);
  useEffect(() => {
    if (prevPhase.current === 'running' && historyStatus?.phase === 'done') load();
    prevPhase.current = historyStatus?.phase;
  }, [historyStatus?.phase, load]);

  if (data === undefined) return <div className="canvas-empty">Loading…</div>;
  if (data === null) return <NotFoundState />;

  return (
    <div className="gallery-screen">
      <section className="gallery-section">
        <h2 className="gallery-section-title">Agents ({data.characters.length})</h2>
        {data.characters.length === 0 ? (
          <div className="canvas-empty">No agents yet.</div>
        ) : (
          <div className="gallery-grid">
            {data.characters.map((c) => {
              const hidden = isHidden(c.id);
              const thumbUrl = firstImageUrl(data.media[c.id]);
              const initial = c.name.trim().charAt(0).toUpperCase() || '?';
              return (
                <div
                  key={c.id}
                  className={`gallery-card ${hidden ? 'is-hidden' : ''}`}
                  onClick={() => navigate({ kind: 'agent', cityId, agentId: c.id, from: { kind: 'gallery', cityId } })}
                >
                  <div className="gallery-card-thumb">{thumbUrl ? <img src={thumbUrl} alt="" /> : initial}</div>
                  <div className="gallery-card-body">
                    <div className="gallery-card-name">{c.name}</div>
                    <div className="gallery-card-subtitle">{c.occupation ?? c.quirk ?? 'resident'}</div>
                    {c.place_name && <div className="gallery-card-grounding">@ {c.place_name}</div>}
                  </div>
                  <button
                    className="gallery-card-toggle"
                    title={hidden ? 'Show in drawer' : 'Hide from drawer'}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(c.id);
                    }}
                  >
                    {hidden ? 'hidden' : 'hide'}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="gallery-section">
        <h2 className="gallery-section-title">Locations ({data.places.length})</h2>
        {data.places.length === 0 ? (
          <div className="canvas-empty">No locations yet.</div>
        ) : (
          <div className="gallery-grid">
            {[...data.places]
              .sort((a, b) => b.founded_year - a.founded_year)
              .map((p) => {
              const hidden = isHidden(p.id);
              const thumbUrl = firstImageUrl(data.media[p.id]);
              const initial = p.name.trim().charAt(0).toUpperCase() || '?';
              return (
                <div
                  key={p.id}
                  className={`gallery-card ${hidden ? 'is-hidden' : ''}`}
                  onClick={() => navigate({ kind: 'place', cityId, placeId: p.id, from: { kind: 'gallery', cityId } })}
                >
                  <div className="gallery-card-thumb">{thumbUrl ? <img src={thumbUrl} alt="" /> : initial}</div>
                  <div className="gallery-card-body">
                    <div className="gallery-card-name">{p.name}</div>
                    <div className="gallery-card-subtitle">
                      {p.place_type} · founded {p.founded_year}
                    </div>
                  </div>
                  <button
                    className="gallery-card-toggle"
                    title={hidden ? 'Show in drawer' : 'Hide from drawer'}
                    onClick={(e) => {
                      e.stopPropagation();
                      toggle(p.id);
                    }}
                  >
                    {hidden ? 'hidden' : 'hide'}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
