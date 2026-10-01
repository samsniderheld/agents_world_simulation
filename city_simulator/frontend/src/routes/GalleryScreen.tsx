import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { agentsApi, history } from '../api/client';
import type { BackgroundResident, HistoryData } from '../api/types';
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
  const { isHidden, toggle, setHidden } = useHiddenEntities(cityId);

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
        <SectionHeader title="Agents" ids={data.characters.map((c) => c.id)} isHidden={isHidden} setHidden={setHidden} />
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
        <SectionHeader title="Locations" ids={data.places.map((p) => p.id)} isHidden={isHidden} setHidden={setHidden} />
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

      <BackgroundSection cityId={cityId} onCharacterMade={load} />
    </div>
  );
}

const PAGE = 60;

// CITY mode's background residents (agents/city/population.py) -- not
// characters, so not on any canvas; up to a thousand of them, hence text
// cards, search and paging. "make a character" gives one a full dossier
// (the same as zooming into a scene does) so they can go on a canvas.
function BackgroundSection({ cityId, onCharacterMade }: { cityId: string; onCharacterMade: () => void }) {
  const [residents, setResidents] = useState<BackgroundResident[] | null>(null);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<'involved' | 'name'>('involved');
  const [shown, setShown] = useState(PAGE);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    agentsApi
      .cityResidents()
      .then((res) => setResidents(res.residents))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(load, [load, cityId]);

  const matching = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (residents ?? []).filter(
      (r) => !q || [r.name, r.occupation, r.work, r.haunt, r.bio].some((v) => v && v.toLowerCase().includes(q)),
    );
    return sort === 'name'
      ? [...list].sort((a, b) => a.name.localeCompare(b.name))
      : [...list].sort((a, b) => (b.hero_interactions ?? -1) - (a.hero_interactions ?? -1) || a.name.localeCompare(b.name));
  }, [residents, query, sort]);

  async function makeCharacter(r: BackgroundResident) {
    setBusy(r.id);
    setError(null);
    try {
      await agentsApi.cityResidentToCharacter(r.id);
      load();
      onCharacterMade();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="gallery-section">
      <div className="gallery-section-header">
        <h2 className="gallery-section-title">
          Background residents ({residents?.length ?? '…'})
          {query && residents ? ` · ${matching.length} match` : ''}
        </h2>
        <input
          className="gallery-search"
          placeholder="Search name, job, place…"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setShown(PAGE);
          }}
        />
        <select className="gallery-sort" value={sort} onChange={(e) => setSort(e.target.value as 'involved' | 'name')}>
          <option value="involved">most involved with heroes</option>
          <option value="name">by name</option>
        </select>
      </div>
      {error && <div className="node-error-text">{error}</div>}
      {residents && residents.length === 0 ? (
        <div className="canvas-empty">
          No background residents yet -- they&rsquo;re created the first time a City Simulation runs with some.
        </div>
      ) : (
        <>
          <div className="gallery-grid">
            {matching.slice(0, shown).map((r) => (
              <div key={r.id} className={`gallery-card gallery-resident ${r.promoted_to ? 'is-promoted' : ''}`}>
                <div className="gallery-card-body">
                  <div className="gallery-card-name">{r.name}</div>
                  <div className="gallery-card-subtitle">
                    {r.age}, {r.occupation}
                    {r.shift === 'night' ? ' · nights' : ''}
                  </div>
                  <div className="gallery-card-grounding">
                    {r.work ? `works @ ${r.work}` : 'works off the map'}
                    {r.haunt ? ` · drinks @ ${r.haunt}` : ''}
                  </div>
                  <div className="gallery-resident-bio">{r.bio}</div>
                  {r.hero_interactions ? (
                    <div className="gallery-resident-badge">{r.hero_interactions}× with heroes in the last run</div>
                  ) : null}
                </div>
                {r.promoted_to ? (
                  <button
                    className="node-run-btn"
                    title="This resident is a character now -- open them"
                    onClick={() => navigate({ kind: 'agent', cityId, agentId: r.promoted_to!, from: { kind: 'gallery', cityId } })}
                  >
                    character: {r.character_name ?? 'open'}
                  </button>
                ) : (
                  <button
                    className="node-run-btn"
                    disabled={busy !== null}
                    title="Write them a full dossier and save them as a character, so they can go on a canvas"
                    onClick={() => makeCharacter(r)}
                  >
                    {busy === r.id ? 'writing their dossier…' : 'make a character'}
                  </button>
                )}
              </div>
            ))}
          </div>
          {matching.length > shown && (
            <button className="node-run-btn gallery-more" onClick={() => setShown((n) => n + PAGE)}>
              show more ({matching.length - shown} left)
            </button>
          )}
        </>
      )}
    </section>
  );
}

// A section's title with its counts, plus one button that hides every card
// in it from the canvas drawers -- or, once they're all hidden, shows them
// all again.
function SectionHeader({
  title,
  ids,
  isHidden,
  setHidden,
}: {
  title: string;
  ids: string[];
  isHidden: (id: string) => boolean;
  setHidden: (ids: string[], hidden: boolean) => void;
}) {
  const hiddenCount = ids.filter(isHidden).length;
  const allHidden = ids.length > 0 && hiddenCount === ids.length;
  return (
    <div className="gallery-section-header">
      <h2 className="gallery-section-title">
        {title} ({ids.length}){hiddenCount > 0 && ` · ${hiddenCount} hidden`}
      </h2>
      {ids.length > 0 && (
        <button
          className="node-run-btn gallery-section-toggle"
          title={allHidden ? 'Show all of these in the canvas drawers again' : 'Hide all of these from the canvas drawers'}
          onClick={() => setHidden(ids, !allHidden)}
        >
          {allHidden ? 'Show all' : 'Hide all'}
        </button>
      )}
    </div>
  );
}
