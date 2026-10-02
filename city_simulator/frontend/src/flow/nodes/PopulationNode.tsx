import { useEffect, useRef, useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { populationApi } from '../../api/client';
import type { PopulationStatus, PopulationStyle } from '../../api/types';
import { NodeShell } from './NodeShell';
import { NumberField } from './NumberField';
import { Port } from './Port';

export interface PopulationNodeData extends Record<string, unknown> {
  // How many locations get a new resident (and an exterior photo if they
  // don't have one yet).
  count: number;
  // Also generate a portrait per resident and an exterior photo per place
  // that has none (default). Off: residents only.
  withImages: boolean;
  // Resolved by pipeline.ts from Style nodes wired into the two style
  // ports -- portraits get characterStyle, exterior photos locationStyle.
  characterStyle?: PopulationStyle;
  locationStyle?: PopulationStyle;
  hasCharacterStyle?: boolean;
  hasLocationStyle?: boolean;
  onChange: (nodeId: string, patch: { count?: number; withImages?: boolean }) => void;
  // Reloads the canvas's city data -- new residents, portraits and
  // exterior photos only show up (drawer, node thumbnails) after that.
  onCityChanged: () => void;
}

export type PopulationNodeType = Node<PopulationNodeData, 'population'>;

// Picks N of the city's locations and gives each a new resident who
// belongs there, with a square portrait, plus a square exterior photo of
// the place if it has none (history/population.py runs it as a background
// job, everything in parallel). Locations aren't created -- a city's places
// come from its history.
export function PopulationNode({ id, data, selected }: NodeProps<PopulationNodeType>) {
  const [status, setStatus] = useState<PopulationStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const wasRunning = useRef(false);
  const running = status?.phase === 'running';

  // Poll while a run is going -- including one started before this node
  // mounted (it's a server-side job, so navigating away doesn't stop it).
  useEffect(() => {
    let cancelled = false;
    const poll = () =>
      populationApi
        .status()
        .then((s) => {
          if (cancelled) return;
          setStatus(s);
          if (wasRunning.current && s.phase !== 'running') data.onCityChanged();
          wasRunning.current = s.phase === 'running';
        })
        .catch(() => {});
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function start() {
    setError(null);
    setStarting(true);
    try {
      const res = await populationApi.start({
        count: data.count,
        characterStyle: data.characterStyle,
        locationStyle: data.locationStyle,
        withImages: data.withImages,
      });
      if (!res.ok) setError(res.error ?? 'failed to start');
      else {
        wasRunning.current = true;
        setStatus(await populationApi.status());
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setStarting(false);
    }
  }

  const shownError = error ?? (status?.phase === 'error' || status?.phase === 'done' ? status.error : null);

  return (
    <NodeShell typeLabel="Population" selected={selected} running={running} error={Boolean(shownError)} wide>
      <div className="node-controls">
        <NumberField value={data.count} min={1} max={50} title="Locations to populate" onCommit={(v) => data.onChange(id, { count: v })} />
        <span className="node-subtitle">locations</span>
      </div>
      <label className="node-checkbox-row">
        <input type="checkbox" checked={data.withImages} onChange={(e) => data.onChange(id, { withImages: e.target.checked })} />
        <span className="node-subtitle">generate portraits and exterior photos</span>
      </label>
      <div className="node-subtitle">
        {data.withImages
          ? 'Each location gets a new resident who belongs there, with a square portrait, plus a square exterior photo if it has none.'
          : 'Each location gets a new resident who belongs there -- no images.'}{' '}
        Locations with no resident come first. All generated in parallel.
      </div>
      {data.withImages && (data.characterStyle || data.locationStyle) && (
        <div className="node-subtitle">
          {data.characterStyle && <div>portraits: {data.characterStyle.prompt || 'style references'}</div>}
          {data.locationStyle && <div>exteriors: {data.locationStyle.prompt || 'style references'}</div>}
        </div>
      )}
      <div className="node-controls">
        <button
          className="node-run-btn"
          disabled={running || starting || data.count < 1}
          onClick={start}
        >
          {running ? 'populating…' : starting ? 'starting…' : '▶ populate'}
        </button>
        {running && (
          <button className="node-run-btn node-delete-btn" onClick={() => populationApi.stop()}>
            stop
          </button>
        )}
      </div>
      {status && status.phase !== 'idle' && (
        <div className="node-grounding">
          {status.done}/{status.total}
          {status.current ? ` · ${status.current}` : status.phase === 'done' ? ' · done' : ''}
        </div>
      )}
      {shownError && <div className="node-error-text">{shownError}</div>}
      {status && status.log.length > 0 && (
        <div className="node-log nowheel">
          {status.log.slice(-12).map((line, i) => (
            <div key={i} className="node-log-row">
              {line}
            </div>
          ))}
        </div>
      )}

      {/* room for the two port rows below, so their labels don't sit on the content */}
      <div style={{ height: 24 }} />
      <Port id="character-style:in" type="style" direction="in" label="char style" optional={!data.hasCharacterStyle} top="calc(100% - 34px)" />
      <Port id="location-style:in" type="style" direction="in" label="place style" optional={!data.hasLocationStyle} top="calc(100% - 14px)" />
    </NodeShell>
  );
}
