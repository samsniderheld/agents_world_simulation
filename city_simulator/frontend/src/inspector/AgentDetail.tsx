import { useEffect, useState } from 'react';
import { city } from '../api/client';
import type { AgentRecord } from '../api/types';
import { eventLine, fmtDate } from './format';
import { MediaGrid } from './MediaGrid';

type Tab = 'bio' | 'plans' | 'events' | 'treatments' | 'media';

// `onMediaChanged` is optional and separate from this component's own
// `record` refetch below -- a caller rendering its own copy of this
// agent's media elsewhere (e.g. AgentScreen's EntityCanvas, which reads
// `record.media` from its own independently-fetched state, not this
// one) needs its own signal to refresh, since deleting here only updates
// *this* component's local `record`.
export function AgentDetail({ characterId, onMediaChanged }: { characterId: string; onMediaChanged?: () => void }) {
  const [record, setRecord] = useState<AgentRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('bio');

  useEffect(() => {
    setRecord(null);
    setError(null);
    city.getAgent(characterId).then(setRecord).catch((e) => setError(String(e)));
  }, [characterId]);

  function refetchAfterMediaChange() {
    city.getAgent(characterId).then(setRecord).catch(() => {});
    onMediaChanged?.();
  }

  if (error) return <div className="inspector-body inspector-empty">{error}</div>;
  if (!record) return <div className="inspector-body inspector-empty">Loading…</div>;

  return (
    <>
      <div className="inspector-header">
        <div className="inspector-title">{record.name}</div>
        <div className="inspector-subtitle">{record.occupation ?? 'resident'}</div>
      </div>
      <div className="inspector-tabs">
        {(['bio', 'plans', 'events', 'treatments', 'media'] as Tab[]).map((t) => (
          <button key={t} className={`inspector-tab ${tab === t ? 'is-active' : ''}`} onClick={() => setTab(t)}>
            {t === 'events' ? 'event log' : t}
          </button>
        ))}
      </div>
      <div className="inspector-body">
        {tab === 'bio' && <Bio record={record} />}
        {tab === 'plans' && <Plans record={record} />}
        {tab === 'events' && <EventLog record={record} />}
        {tab === 'treatments' && <Treatments record={record} />}
        {tab === 'media' && <MediaGrid items={newestFirst(record.media)} entityId={characterId} onDeleted={refetchAfterMediaChange} />}
      </div>
    </>
  );
}

function Bio({ record }: { record: AgentRecord }) {
  return (
    <div>
      <div className="inspector-kv">
        <b>age</b> {record.age ?? '—'} · <b>@</b> {record.place_name ?? '—'}
      </div>
      {record.quirk && <p style={{ fontStyle: 'italic', color: 'var(--accent)' }}>{record.quirk}</p>}
      <p>{record.bio}</p>
      {[...(record.history ?? [])].sort((a, b) => b.year - a.year).map((h, i) => (
        <div className="inspector-entry" key={i}>
          <span className="inspector-entry-year">{h.year}</span>
          {h.gospel_text}
        </div>
      ))}
    </div>
  );
}

// Everything in an agent's record is appended as it happens (citystate/
// store.py), so stored order is oldest-first; the panel shows newest-first.
// Only the *list* is flipped -- a single plan's own steps keep their order.
function newestFirst<T>(items: T[]): T[] {
  return [...items].reverse();
}

function Plans({ record }: { record: AgentRecord }) {
  if (record.plans.length === 0) return <div className="inspector-empty">No plans yet.</div>;
  return (
    <div>
      {newestFirst(record.plans).map((p, i) => (
        <div className="inspector-entry" key={i}>
          <div className="inspector-kv">
            <b>tick {p.tick}</b> · run started {fmtDate(p.run_started_at)}
          </div>
          <ol style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {p.items.map((item, j) => (
              <li key={j}>{item}</li>
            ))}
          </ol>
        </div>
      ))}
    </div>
  );
}

function EventLog({ record }: { record: AgentRecord }) {
  if (record.runs.length === 0) return <div className="inspector-empty">No runs yet.</div>;
  return (
    <div>
      {newestFirst(record.runs).map((run, i) => (
        <div key={i}>
          <div className="inspector-run-header">run · {fmtDate(run.started_at)}</div>
          {newestFirst(run.events).map((e, j) => (
            <div className="inspector-event-row" key={j}>
              <span className="inspector-event-badge">{e.kind}</span>
              <span>{eventLine(e)}</span>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function Treatments({ record }: { record: AgentRecord }) {
  if (record.treatments.length === 0) return <div className="inspector-empty">No treatments generated yet.</div>;
  return (
    <div>
      {newestFirst(record.treatments).map((t, i) => (
        <div className="inspector-entry" key={i}>
          <div className="inspector-kv">{fmtDate(t.created_at)}</div>
          <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--sans)', fontSize: 13 }}>{t.text}</pre>
        </div>
      ))}
    </div>
  );
}
