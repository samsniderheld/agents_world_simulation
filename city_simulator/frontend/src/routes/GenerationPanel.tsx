import { useEffect, useRef, useState } from 'react';
import { history } from '../api/client';
import type { JobStatus } from '../api/types';

const STAGE_LABELS: Record<string, { label: string; detail: string }> = {
  history: { label: 'History', detail: 'figures, places and events, era by era -- names and buildings written by the model' },
  residents: { label: 'Residents', detail: 'a dossier and life story for each' },
  summary: { label: 'Summary', detail: "the city's story, in a few paragraphs" },
};
const LOG_KEEP = 200;

// The Cities screen's view of a city being generated (history/jobs.py):
// which stage it's in, how far through, how long it's been going, and the
// generation log as it's written. Also shows a failed run's error, which
// would otherwise be invisible.
export function GenerationPanel({ status }: { status: JobStatus }) {
  const [lines, setLines] = useState<string[]>([]);
  const sinceRef = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);
  const running = status.phase === 'running';

  // Poll the log incrementally while running; read it once otherwise
  // (a failed run's last lines say where it stopped).
  useEffect(() => {
    let cancelled = false;
    sinceRef.current = 0;
    setLines([]);
    const load = () =>
      history
        .log(sinceRef.current)
        .then((res) => {
          if (cancelled || !res.lines.length) return;
          sinceRef.current = res.next;
          setLines((prev) => [...prev, ...res.lines].slice(-LOG_KEEP));
        })
        .catch(() => {});
    load();
    const id = running ? setInterval(load, 1500) : null;
    return () => {
      cancelled = true;
      if (id) clearInterval(id);
    };
  }, [running]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  const p = status.progress;
  const current = p?.stage ? p.stages.indexOf(p.stage) : -1;

  return (
    <section className={`gen-panel ${status.phase === 'error' ? 'is-error' : ''}`} aria-live="polite">
      <header className="gen-head">
        <h2 className="gen-title">{running ? 'Building a new city' : 'City generation failed'}</h2>
        {running && p?.elapsed_seconds != null && <span className="gen-elapsed">{fmtElapsed(p.elapsed_seconds)}</span>}
      </header>

      {status.phase === 'error' && <div className="node-error-text">{status.error ?? 'unknown error'}</div>}

      {running && (
        <ol className="gen-stages">
          {(p?.stages ?? Object.keys(STAGE_LABELS)).map((s, i) => {
            const state = current < 0 ? 'pending' : i < current ? 'done' : i === current ? 'active' : 'pending';
            const info = STAGE_LABELS[s] ?? { label: s, detail: '' };
            const counted = state === 'active' && p && p.total > 0;
            return (
              <li key={s} className={`gen-stage is-${state}`}>
                <span className="gen-mark" aria-hidden="true">
                  {state === 'done' ? '✓' : i + 1}
                </span>
                <div className="gen-stage-body">
                  <div className="gen-stage-name">
                    {info.label}
                    {counted && (
                      <span className="gen-count">
                        {p!.done} / {p!.total}
                      </span>
                    )}
                  </div>
                  <div className="gen-stage-detail">{info.detail}</div>
                  {state === 'active' && (
                    <div className={`gen-bar ${counted ? '' : 'is-indeterminate'}`}>
                      <div className="gen-bar-fill" style={counted ? { width: `${(100 * p!.done) / p!.total}%` } : undefined} />
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {lines.length > 0 && (
        <div className="gen-log" ref={logRef}>
          {lines.map((l, i) => (
            <div key={i}>{l}</div>
          ))}
        </div>
      )}
    </section>
  );
}

function fmtElapsed(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h ? `${h}h ${m}m` : m ? `${m}m ${String(sec).padStart(2, '0')}s` : `${sec}s`;
}
