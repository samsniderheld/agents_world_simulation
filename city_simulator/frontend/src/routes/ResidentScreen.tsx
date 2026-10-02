import { useCallback, useEffect, useState } from 'react';
import { agentsApi, history } from '../api/client';
import type { ResidentDetail } from '../api/types';
import { navigate } from './router';
import './gallery.css';

// One CITY-mode background resident (agents/city/zoom.py's
// resident_detail): who they are, and what the latest CITY run saw of them
// -- dealings with heroes, who they knew best, their last memories, where
// they were. "make a hero" turns them into a saved character, the same way
// the Gallery card's button and zoom-in do.
export function ResidentScreen({ cityId, residentId }: { cityId: string; residentId: string }) {
  const [r, setR] = useState<ResidentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Activate the city first (a bookmark or refresh can land here directly),
  // like GalleryScreen does.
  const load = useCallback(() => {
    history
      .activateCity(cityId)
      .then(() => agentsApi.cityResident(residentId))
      .then(setR)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [cityId, residentId]);
  useEffect(load, [load]);

  async function makeHero() {
    setBusy(true);
    setError(null);
    try {
      await agentsApi.cityResidentToCharacter(residentId);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (error && !r) return <div className="canvas-empty">{error}</div>;
  if (!r) return <div className="canvas-empty">Loading…</div>;
  const run = r.run;

  return (
    <div className="gallery-screen resident-screen">
      <div className="resident-head">
        <div>
          <h1 className="resident-name">{r.name}</h1>
          <div className="gallery-card-subtitle">
            {r.age}, {r.occupation}
            {r.shift === 'night' ? ' · works nights' : ''} · background resident
          </div>
          <div className="gallery-card-grounding">
            {r.work ? `works @ ${r.work}` : 'works off the map'}
            {r.haunt ? ` · spends free time @ ${r.haunt}` : ''}
            {r.home ? ` · lives @ ${r.home}` : ''}
          </div>
        </div>
        {r.promoted_to ? (
          <button
            className="node-run-btn"
            onClick={() => navigate({ kind: 'agent', cityId, agentId: r.promoted_to!, from: { kind: 'resident', cityId, residentId } })}
          >
            open hero: {r.character_name ?? r.name}
          </button>
        ) : (
          <button className="node-run-btn" disabled={busy} onClick={makeHero}>
            {busy ? 'writing their dossier…' : 'make a hero'}
          </button>
        )}
      </div>
      {error && <div className="node-error-text">{error}</div>}
      <p className="resident-bio">{r.bio}</p>
      {!r.promoted_to && (
        <div className="resident-note">
          Make a hero to give {r.name.split(' ')[0]} a full dossier (looks, wardrobe, a secret) and save them as a
          character: a hero in CITY runs, an Agent you can put on any canvas
          {run?.memories.length ? ', remembering what the last run saw them do' : ''}.
        </div>
      )}

      {!run ? (
        <div className="resident-note">No City Simulation has run yet, so there&rsquo;s nothing more to show.</div>
      ) : !run.in_run ? (
        <div className="resident-note">{r.name} wasn&rsquo;t part of the latest City Simulation run.</div>
      ) : (
        <div className="resident-columns">
          <section>
            <h2 className="gallery-section-title">The last run</h2>
            <div className="resident-facts">
              {run.became_hero && <div>Promoted to a hero during the run.</div>}
              {run.hero_interactions != null && <div>{run.hero_interactions} dealings with heroes</div>}
              {run.schedule && <div>day planned by {run.schedule === 'llm' ? 'the model' : 'an occupation template'}</div>}
            </div>
            {run.acquaintances.length > 0 && (
              <>
                <h3 className="resident-sub">Knew best</h3>
                <ul className="resident-list">
                  {run.acquaintances.map((a) => (
                    <li key={a.name}>
                      {a.name}
                      {a.hero ? ' (hero)' : ''} -- {a.count}×
                    </li>
                  ))}
                </ul>
              </>
            )}
            {run.memories.length > 0 && (
              <>
                <h3 className="resident-sub">Last memories</h3>
                <ul className="resident-list">
                  {[...run.memories].reverse().map((m, i) => (
                    <li key={i}>
                      <span className="resident-time">{m.time}</span> {m.text}
                    </li>
                  ))}
                </ul>
              </>
            )}
          </section>
          <section>
            <h2 className="gallery-section-title">Where they were</h2>
            <ul className="resident-list">
              {run.stays.map((s, i) => (
                <li key={i}>
                  <span className="resident-time">
                    {s.from}–{s.until}
                  </span>{' '}
                  {s.place}
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </div>
  );
}
