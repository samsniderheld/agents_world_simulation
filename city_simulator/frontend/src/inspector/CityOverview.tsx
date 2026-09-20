import { useEffect, useState } from 'react';
import { history } from '../api/client';
import type { HistoryData } from '../api/types';
import { useJobStore } from '../state/jobStore';
import { fmtDate } from './format';

type Tab = 'overview' | 'chronicle' | 'log';

export function CityOverview({ data }: { data: HistoryData }) {
  const [tab, setTab] = useState<Tab>('overview');

  return (
    <>
      <div className="inspector-header">
        <div className="inspector-title">The City</div>
        <div className="inspector-subtitle">generated {fmtDate(data.generated_at)}</div>
      </div>
      <div className="inspector-tabs">
        {(['overview', 'chronicle', 'log'] as Tab[]).map((t) => (
          <button key={t} className={`inspector-tab ${tab === t ? 'is-active' : ''}`} onClick={() => setTab(t)}>
            {t === 'log' ? 'generation log' : t}
          </button>
        ))}
      </div>
      <div className="inspector-body">
        {tab === 'overview' && <Overview data={data} />}
        {tab === 'chronicle' && <Chronicle data={data} />}
        {tab === 'log' && <GenerationLog />}
      </div>
    </>
  );
}

function Overview({ data }: { data: HistoryData }) {
  return (
    <div>
      <p>{data.summary || 'No summary generated for this city.'}</p>
      <div className="inspector-stats">
        <div>
          <b>{data.figures.length}</b> figures
        </div>
        <div>
          <b>{data.places.length}</b> places
        </div>
        <div>
          <b>{data.characters.length}</b> residents
        </div>
        <div>
          <b>{data.events.length}</b> events
        </div>
      </div>
    </div>
  );
}

function Chronicle({ data }: { data: HistoryData }) {
  const figureName = new Map(data.figures.map((f) => [f.id, f.name]));
  const placeName = new Map(data.places.map((p) => [p.id, p.name]));
  const sorted = [...data.events].sort((a, b) => a.year - b.year);

  return (
    <div>
      {sorted.map((e) => (
        <div className="inspector-entry" key={e.id}>
          <span className="inspector-entry-year">{e.year}</span>
          {e.gospel_text}
          <div className="inspector-kv">
            {e.figure_id && <span>{figureName.get(e.figure_id) ?? e.figure_id}</span>}
            {e.figure_id && e.place_id && <span> · </span>}
            {e.place_id && <span>{placeName.get(e.place_id) ?? e.place_id}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function GenerationLog() {
  const [lines, setLines] = useState<string[]>([]);
  const historyStatus = useJobStore((s) => s.historyStatus);

  useEffect(() => {
    let cancelled = false;
    const load = () => history.log().then((res) => !cancelled && setLines(res.lines));
    load();
    const running = historyStatus?.phase === 'running';
    const id = running ? setInterval(load, 2000) : null;
    return () => {
      cancelled = true;
      if (id) clearInterval(id);
    };
  }, [historyStatus?.phase]);

  if (lines.length === 0) return <div className="inspector-empty">No generation log yet.</div>;
  return (
    <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'var(--mono)', fontSize: 12 }}>{lines.join('\n')}</pre>
  );
}
