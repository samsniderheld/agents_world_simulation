import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { agentsApi, history } from '../api/client';
import type { Person } from '../api/types';
import { firstImageUrl } from '../flow/entityNodeKit';
import { navigate } from '../routes/router';
import type { Scope } from '../routes/router';
import { eventLine, eventOutcome, fmtDate } from './format';
import { MediaGrid } from './MediaGrid';
import { SheetView } from './SheetView';
import './character.css';

// Anyone in the city -- a hero or a background resident -- in one view,
// character sheet first (GET /api/agents/people/<id>, agents/people.py).
// The same sections for both: a resident's are just thinner until they're
// made a hero. `layout` "page" is the full-screen character page (two
// columns); "drawer" is the canvas's side panel (one column, with a link
// to the page).
export function CharacterView({
  personId,
  cityId,
  layout,
  activate = false,
  from,
  onMediaChanged,
  onLoaded,
  headerExtra,
}: {
  personId: string;
  cityId: string;
  layout: 'page' | 'drawer';
  // Activate cityId before reading (a page reached by bookmark/refresh).
  activate?: boolean;
  // Where the page was opened from, for links to other people's pages.
  from?: Scope;
  onMediaChanged?: () => void;
  onLoaded?: (person: Person) => void;
  // Page-only controls next to the header actions (e.g. the canvas switch).
  headerExtra?: ReactNode;
}) {
  const [person, setPerson] = useState<Person | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    const ready = activate ? history.activateCity(cityId) : Promise.resolve();
    return ready
      .then(() => agentsApi.person(personId))
      .then((p) => {
        setPerson(p);
        setError(null);
        onLoaded?.(p);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- onLoaded is a notification, not an input
  }, [activate, cityId, personId]);

  useEffect(() => {
    setPerson(null);
    load();
  }, [load]);

  async function makeHero() {
    if (!person) return;
    setBusy(true);
    setError(null);
    try {
      const { character } = await agentsApi.cityResidentToCharacter(person.id);
      if (layout === 'page') navigate({ kind: 'agent', cityId, agentId: character.id, from });
      else await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function openPerson(id: string) {
    if (id.startsWith('char_')) navigate({ kind: 'agent', cityId, agentId: id, from });
    else navigate({ kind: 'resident', cityId, residentId: id, from });
  }

  if (error && !person) return <div className={layout === 'page' ? 'canvas-empty' : 'inspector-body inspector-empty'}>{error}</div>;
  if (!person) return <div className={layout === 'page' ? 'canvas-empty' : 'inspector-body inspector-empty'}>Loading…</div>;

  const p = person;
  const portrait = firstImageUrl(p.media);
  const pageScope: Scope =
    p.kind === 'hero' ? { kind: 'agent', cityId, agentId: p.id } : { kind: 'resident', cityId, residentId: p.id };

  const header = (
    <header className="char-head">
      <div className="char-portrait">{portrait ? <img src={portrait} alt="" /> : p.name.trim().charAt(0).toUpperCase()}</div>
      <div className="char-id">
        <h1 className="char-name">{p.name}</h1>
        <div className="char-line">
          {[p.age, p.occupation].filter((x) => x != null && x !== '').join(', ')}
          {p.shift === 'night' ? ' · works nights' : ''}
          <span className={`char-kind is-${p.kind}`}>{p.kind === 'hero' ? 'hero' : 'background resident'}</span>
        </div>
        {p.places.length > 0 && (
          <div className="char-places">{p.places.map((pl) => `${pl.role} ${pl.place}`).join(' · ')}</div>
        )}
        {p.quirk && <div className="char-quirk">{p.quirk}</div>}
      </div>
      <div className="char-actions">
        {headerExtra}
        {layout === 'drawer' && (
          <button className="node-run-btn" onClick={() => navigate(pageScope)}>
            open page
          </button>
        )}
        {p.can_make_hero && (
          <button
            className="node-run-btn"
            disabled={busy}
            onClick={makeHero}
            title="Write a full dossier (looks, wardrobe, a secret) and save them as a character: a hero in CITY runs, an Agent for any canvas"
          >
            {busy ? 'writing their dossier…' : 'make a hero'}
          </button>
        )}
      </div>
    </header>
  );

  const sheet = (
    <Section title="Character sheet" className="char-sheet">
      <SheetView sheet={p.sheet} feelings={false} />
    </Section>
  );

  const story = (
    <Section title="Story">
      {p.bio ? <p className="char-bio">{p.bio}</p> : <Empty>No biography yet.</Empty>}
      {p.life.length > 0 && (
        <ul className="char-list">
          {p.life.map((h, i) => (
            <li key={i}>
              <span className="char-time">{h.year}</span> {h.text}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );

  const peopleSection = (
    <Section title="People" count={p.people.length}>
      {p.people.length === 0 ? (
        <Empty>Nobody yet -- the people they meet, and how they feel about them, show up here.</Empty>
      ) : (
        <ul className="char-people">
          {p.people.map((x) => (
            <li key={x.name}>
              {x.id ? (
                <button className="char-link" onClick={() => openPerson(x.id!)}>
                  {x.name}
                </button>
              ) : (
                <span>{x.name}</span>
              )}
              {x.hero && <span className="char-tag">hero</span>}
              <span className={`char-attitude is-${x.attitude_label}`}>
                {x.attitude ? `${x.attitude_label} ${x.attitude > 0 ? '+' : ''}${x.attitude}` : 'neutral'}
              </span>
              {x.meetings > 0 && <span className="char-dim">met {x.meetings}×</span>}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );

  const memories = (
    <Section title="Memories" count={p.memories.length}>
      {p.memories.length === 0 ? (
        <Empty>No memories yet -- they come from simulation runs.</Empty>
      ) : (
        <Expandable
          items={p.memories}
          limit={layout === 'page' ? 30 : 15}
          render={(m, i) => (
            <li key={i} className={m.importance != null && m.importance >= 7 ? 'is-important' : undefined}>
              <span className="char-time">{m.time}</span> {m.text}
              {m.kind && m.kind !== 'observation' && <span className="char-tag">{m.kind}</span>}
            </li>
          )}
        />
      )}
    </Section>
  );

  const plans = (
    <Section title="Plans" count={p.plans.length}>
      {p.plans.length === 0 ? (
        <Empty>{p.kind === 'resident' ? 'Residents follow a daily routine; a hero makes plans.' : 'No plans yet.'}</Empty>
      ) : (
        <Expandable
          items={p.plans}
          limit={3}
          render={(pl, i) => (
            <li key={i}>
              <div className="char-dim">
                {fmtDate(pl.run_started_at)} · tick {pl.tick}
              </div>
              <ol className="char-plan">
                {pl.items.map((item, j) => (
                  <li key={j}>{item}</li>
                ))}
              </ol>
            </li>
          )}
        />
      )}
    </Section>
  );

  const lastRun = (
    <Section title="Last City Simulation">
      {!p.last_city_run ? (
        <Empty>Not in the latest City Simulation run.</Empty>
      ) : (
        <>
          <div className="char-dim">
            {fmtDate(p.last_city_run.started_at)}
            {p.last_city_run.hero_interactions != null ? ` · ${p.last_city_run.hero_interactions} dealings with heroes` : ''}
            {p.last_city_run.schedule ? ` · day planned by ${p.last_city_run.schedule === 'llm' ? 'the model' : 'a template'}` : ''}
          </div>
          <ul className="char-list">
            {p.last_city_run.stays.map((s, i) => (
              <li key={i}>
                <span className="char-time">
                  {s.from}–{s.until}
                </span>{' '}
                {s.place}
              </li>
            ))}
          </ul>
        </>
      )}
    </Section>
  );

  const media = (
    <Section title="Media" count={p.media.length}>
      {p.media.length === 0 ? (
        <Empty>{p.kind === 'resident' ? 'Make them a hero to give them a portrait.' : 'No pictures or video yet.'}</Empty>
      ) : (
        <MediaGrid
          items={p.media}
          entityId={p.id}
          onDeleted={() => {
            load();
            onMediaChanged?.();
          }}
        />
      )}
    </Section>
  );

  const treatments = (
    <Section title="Treatments" count={p.treatments.length}>
      {p.treatments.length === 0 ? (
        <Empty>No treatments yet.</Empty>
      ) : (
        p.treatments.map((t, i) => (
          <details key={i} className="char-fold" open={i === 0 && layout === 'page'}>
            <summary>{fmtDate(t.created_at)}</summary>
            <pre className="char-treatment">{t.text}</pre>
          </details>
        ))
      )}
    </Section>
  );

  const runLog = (
    <Section title="Run log" count={p.runs.length}>
      {p.runs.length === 0 ? (
        <Empty>{p.kind === 'resident' ? 'A resident’s runs show as memories above.' : 'No runs yet.'}</Empty>
      ) : (
        p.runs.map((run, i) => (
          <details key={i} className="char-fold">
            <summary>
              {run.mode === 'city' ? 'city run' : 'scene run'}
              {run.dm ? ' · dice & DM' : ''} · {fmtDate(run.started_at)}{' '}
              <span className="char-dim">({run.events.length ? `${run.events.length} events` : 'memories only'})</span>
            </summary>
            {run.events.map((e, j) => (
              <div className="inspector-event-row" key={j}>
                <span className="inspector-event-badge" data-outcome={eventOutcome(e)}>
                  {e.kind}
                </span>
                <span>{eventLine(e)}</span>
              </div>
            ))}
          </details>
        ))
      )}
    </Section>
  );

  if (layout === 'drawer') {
    return (
      <div className="char-view is-drawer">
        {header}
        {error && <div className="node-error-text">{error}</div>}
        {sheet}
        {story}
        {memories}
        {peopleSection}
        {plans}
        {lastRun}
        {media}
        {treatments}
        {runLog}
      </div>
    );
  }
  return (
    <div className="char-view is-page">
      {header}
      {error && <div className="node-error-text">{error}</div>}
      <div className="char-columns">
        <div className="char-column">
          {sheet}
          {story}
          {peopleSection}
        </div>
        <div className="char-column">
          {memories}
          {plans}
          {lastRun}
        </div>
      </div>
      {media}
      <div className="char-columns">
        <div className="char-column">{treatments}</div>
        <div className="char-column">{runLog}</div>
      </div>
    </div>
  );
}

function Section({ title, count, className, children }: { title: string; count?: number; className?: string; children: ReactNode }) {
  return (
    <section className={`char-section ${className ?? ''}`}>
      <h2 className="char-section-title">
        {title}
        {count ? <span className="char-count">{count}</span> : null}
      </h2>
      {children}
    </section>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div className="char-empty">{children}</div>;
}

function Expandable<T>({ items, limit, render }: { items: T[]; limit: number; render: (item: T, i: number) => ReactNode }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, limit);
  return (
    <>
      <ul className="char-list">{shown.map(render)}</ul>
      {items.length > limit && (
        <button className="char-more" onClick={() => setAll(!all)}>
          {all ? 'show fewer' : `show all ${items.length}`}
        </button>
      )}
    </>
  );
}
