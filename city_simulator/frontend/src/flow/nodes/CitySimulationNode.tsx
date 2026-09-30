import { useEffect, useRef, useState } from 'react';
import type { UIEvent } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { agentsApi } from '../../api/client';
import type { AgentEvent, CityMetrics, CityZoomOptions, CityZoomResult } from '../../api/types';
import { eventLine } from '../../inspector/format';
import { useJobStore } from '../../state/jobStore';
import { NodeShell } from './NodeShell';
import { NumberField } from './NumberField';
import { Port } from './Port';

// CITY mode (agents/city/): wired-in agents are the HERO tier (full
// cognition); `backgroundCount` more residents are generated from the
// city's own data and follow schedules, touching the LLM only rarely.
// SCENE mode's Simulation node is a separate node and unchanged.
export interface CitySimulationNodeData extends Record<string, unknown> {
  backgroundCount: number;
  // A CITY hardware profile (hardware.py's CITY_PROFILES) or "auto".
  profile: string;
  // Per-tier provider/model overrides; blank = the profile's choice.
  heroProvider: string;
  heroModel: string;
  backgroundProvider: string;
  backgroundModel: string;
  ticks: number;
  tickMinutes: number;
  startTime: string;
  directive: string;
  // Append each hero's events to their saved record, as a SCENE run does.
  persistHeroMemories: boolean;
  // Resolved by pipeline.ts from the agents:in / place:in edges.
  agentNames: string[];
  placeId?: string;
  placeName?: string;
  onChange: (nodeId: string, patch: Partial<CitySimulationNodeData>) => void;
  // Creates a pre-wired Simulation node for a zoomed-in scene.
  onZoomIn: (nodeId: string, result: CityZoomResult) => void;
}

export type CitySimulationNodeType = Node<CitySimulationNodeData, 'citysim'>;

interface NotableResident {
  name: string;
  occupation: string;
  location: string;
  hero_interactions: number;
}

const LOG_KINDS = new Set(['action', 'dialogue', 'react', 'status', 'promotion', 'tick_summary']);
const LOG_KINDS_WITH_BACKGROUND = new Set([...LOG_KINDS, 'move', 'encounter', 'schedules', 'moves']);

const PROVIDERS = [
  { value: '', label: 'profile default' },
  { value: 'ollama', label: 'Ollama (local)' },
  { value: 'openai', label: 'OpenAI-compatible (vLLM / SGLang / llama.cpp / MLX)' },
  { value: 'claude', label: 'Claude (API)' },
];

const CITY_PROFILES = [
  { value: 'auto', label: 'auto-detect hardware' },
  { value: 'mac', label: 'Mac (Ollama, ≤64 GB)' },
  { value: 'rtx5090', label: 'RTX 5090 (vLLM)' },
  { value: 'h100', label: 'H100 (vLLM)' },
];

export function CitySimulationNode({ id, data, selected, height }: NodeProps<CitySimulationNodeType>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [directive, setDirective] = useState(data.directive);
  const [heroModel, setHeroModel] = useState(data.heroModel);
  const [backgroundModel, setBackgroundModel] = useState(data.backgroundModel);
  const [recent, setRecent] = useState<AgentEvent[]>([]);
  const [watching, setWatching] = useState(false);
  // Include background residents' moves/encounters in the log (the server
  // sends heroes + run-level events by default).
  const [showBackground, setShowBackground] = useState(false);
  const cursorRef = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const agentsState = useJobStore((s) => s.agentsState);
  const [detected, setDetected] = useState<string | null>(null);

  useEffect(() => {
    agentsApi
      .cityProfiles()
      .then((res) => setDetected(res.detected))
      .catch(() => {});
  }, []);

  const globallyRunning = agentsState?.status.phase === 'running';
  const isCityRun = agentsState?.status.mode === 'city';
  const cityRunning = globallyRunning && isCityRun;
  const live = watching || cityRunning;

  useEffect(() => {
    if (!live) return;
    let cancelled = false;
    let busy = false;
    const poll = async () => {
      if (busy) return;
      busy = true;
      try {
        const state = await agentsApi.state();
        const res = await agentsApi.events(cursorRef.current, showBackground ? 'all' : 'hero');
        if (cancelled) return;
        cursorRef.current = res.next;
        if (res.events.length) setRecent((prev) => [...prev, ...(res.events as AgentEvent[])].slice(-2000));
        if (state.status.phase !== 'running') setWatching(false);
      } catch {
        // transient -- the next poll retries
      } finally {
        busy = false;
      }
    };
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [live, showBackground]);

  const shownKinds = showBackground ? LOG_KINDS_WITH_BACKGROUND : LOG_KINDS;
  const visibleEvents = recent.filter((e) => shownKinds.has(e.kind));

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visibleEvents.length]);

  function onLogScroll(e: UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }

  const change = (patch: Partial<CitySimulationNodeData>) => data.onChange(id, patch);

  async function run() {
    setError(null);
    setPending(true);
    setRecent([]);
    cursorRef.current = 0;
    try {
      const res = await agentsApi.runCity({
        agentNames: data.agentNames,
        backgroundCount: data.backgroundCount,
        profile: data.profile,
        heroProvider: data.heroProvider || undefined,
        heroModel: heroModel.trim() || undefined,
        backgroundProvider: data.backgroundProvider || undefined,
        backgroundModel: backgroundModel.trim() || undefined,
        ticks: data.ticks,
        tickMinutes: data.tickMinutes,
        startTime: data.startTime,
        directive,
        placeId: data.placeId,
        persistHeroMemories: data.persistHeroMemories,
      });
      if (!res.ok) setError(res.error ?? 'failed to start');
      else setWatching(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  const statusError = cityRunning || !isCityRun ? null : agentsState?.status.error;
  const paused = Boolean(agentsState?.meta?.paused);
  // Zoom in from a finished or paused CITY run.
  const canZoom = isCityRun && (!globallyRunning || paused);
  const notable = (isCityRun ? (agentsState?.meta?.notable as NotableResident[] | undefined) : undefined) ?? [];

  async function promote(name: string) {
    const res = await agentsApi.cityPromote(name).catch((e) => ({ ok: false, error: String(e) }));
    if (!res.ok) setError(res.error ?? 'promotion failed');
  }
  const heroes = data.agentNames.length;

  return (
    <NodeShell typeLabel="City Simulation" selected={selected} running={cityRunning} error={Boolean(error || statusError)} wide>
      <div className="node-title">City Simulation</div>
      <div className="node-grounding">
        {heroes ? `${heroes} hero${heroes === 1 ? '' : 'es'} connected` : 'no heroes wired: the city’s generated residents are the heroes'}
      </div>
      <div className="node-grounding">{data.placeName ? `heroes convene: ${data.placeName}` : 'everyone starts at their own place'}</div>

      <div className="node-controls">
        <NumberField
          value={data.backgroundCount}
          min={0}
          max={1000}
          title="Background residents"
          onCommit={(v) => change({ backgroundCount: v })}
        />
        <span className="node-subtitle">background residents</span>
      </div>

      <textarea
        className="node-prompt-input"
        rows={2}
        value={directive}
        placeholder="Direction for the heroes (name background residents to include them)…"
        onChange={(e) => setDirective(e.target.value)}
        onBlur={() => directive !== data.directive && change({ directive })}
      />

      <div className="node-controls">
        <span className="node-subtitle">hardware</span>
        <select className="node-select" value={data.profile} onChange={(e) => change({ profile: e.target.value })}>
          {CITY_PROFILES.map((p) => (
            <option key={p.value} value={p.value}>
              {p.value === 'auto' && detected ? `auto-detect (${detected})` : p.label}
            </option>
          ))}
        </select>
      </div>
      <TierRow
        label="heroes"
        provider={data.heroProvider}
        model={heroModel}
        onProvider={(v) => {
          setHeroModel('');
          change({ heroProvider: v, heroModel: '' });
        }}
        onModel={setHeroModel}
        onModelCommit={() => heroModel !== data.heroModel && change({ heroModel })}
      />
      <TierRow
        label="background"
        provider={data.backgroundProvider}
        model={backgroundModel}
        onProvider={(v) => {
          setBackgroundModel('');
          change({ backgroundProvider: v, backgroundModel: '' });
        }}
        onModel={setBackgroundModel}
        onModelCommit={() => backgroundModel !== data.backgroundModel && change({ backgroundModel })}
      />

      <div className="node-controls">
        <span className="node-subtitle">ticks</span>
        <NumberField value={data.ticks} min={1} max={1000} title="Number of ticks" onCommit={(v) => change({ ticks: v })} />
        <span className="node-subtitle">×</span>
        <NumberField value={data.tickMinutes} min={1} max={1440} title="Simulated minutes per tick" onCommit={(v) => change({ tickMinutes: v })} />
        <span className="node-subtitle">min from</span>
        <input
          className="node-select"
          type="time"
          value={data.startTime}
          title="Simulated time of day the run starts at"
          onChange={(e) => e.target.value && change({ startTime: e.target.value })}
        />
      </div>
      <label className="node-checkbox-row">
        <input type="checkbox" checked={data.persistHeroMemories} onChange={(e) => change({ persistHeroMemories: e.target.checked })} />
        <span className="node-subtitle">persist hero memories (SCENE runs remember this run)</span>
      </label>

      <div className="node-controls">
        <button className="node-run-btn" disabled={globallyRunning || pending} onClick={run}>
          {cityRunning ? 'running…' : '▶ run city'}
        </button>
        {cityRunning && (
          <button className="node-run-btn" onClick={() => (paused ? agentsApi.cityResume() : agentsApi.cityPause())}>
            {paused ? 'resume' : 'pause'}
          </button>
        )}
        {cityRunning && (
          <button className="node-run-btn node-delete-btn" onClick={() => agentsApi.stop()}>
            stop
          </button>
        )}
      </div>
      {isCityRun && agentsState?.population && (
        <div className="node-subtitle">
          {agentsState.population.heroes} heroes · {agentsState.population.background} background
          {paused ? ' · paused' : ''}
        </div>
      )}

      {cityRunning && notable.length > 0 && (
        <details className="node-subtitle">
          <summary>residents dealing with the heroes ({notable.length})</summary>
          {notable.map((r) => (
            <div key={r.name} className="node-controls">
              <span>
                {r.name}, {r.occupation} @ {r.location}
                {r.hero_interactions ? ` · ${r.hero_interactions}×` : ''}
              </span>
              <button className="node-run-btn" title="Make this resident a hero from the next tick" onClick={() => promote(r.name)}>
                promote
              </button>
            </div>
          ))}
        </details>
      )}

      {(error || statusError) && <div className="node-error-text">{error || statusError}</div>}

      {isCityRun && agentsState?.metrics && <Metrics m={agentsState.metrics} />}

      {canZoom && <ZoomIn nodeId={id} onZoomIn={data.onZoomIn} />}

      {(live || recent.length > 0) && (
        <label className="node-checkbox-row">
          <input
            type="checkbox"
            checked={showBackground}
            onChange={(e) => {
              // Re-read the (ring-buffered) log from the start with the new filter.
              cursorRef.current = 0;
              setRecent([]);
              setShowBackground(e.target.checked);
              if (!live) setWatching(true);
            }}
          />
          <span className="node-subtitle">show background residents in the log</span>
        </label>
      )}

      {visibleEvents.length > 0 && (
        <div className="node-log nowheel" ref={logRef} onScroll={onLogScroll} style={{ maxHeight: height ? undefined : 240 }}>
          {visibleEvents.map((e, i) => (
            <div className="node-log-row" key={i}>
              <span className="node-log-badge">{e.kind}</span>
              {e.agent && <span>{e.agent}: </span>}
              {eventLine(e)}
            </div>
          ))}
        </div>
      )}

      <Port id="agents:in" type="agent" direction="in" label="heroes" top="calc(100% - 34px)" />
      <Port id="place:in" type="place" direction="in" label="place" optional={!data.placeName} top="calc(100% - 14px)" />
      <Port id="run:out" type="run" direction="out" label="run" top="calc(100% - 24px)" />
    </NodeShell>
  );
}

function TierRow(props: {
  label: string;
  provider: string;
  model: string;
  onProvider: (v: string) => void;
  onModel: (v: string) => void;
  onModelCommit: () => void;
}) {
  return (
    <div className="node-controls">
      <span className="node-subtitle">{props.label}</span>
      <select className="node-select" value={props.provider} onChange={(e) => props.onProvider(e.target.value)}>
        {PROVIDERS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
      <input
        className="node-select"
        placeholder="model (profile default)"
        value={props.model}
        onChange={(e) => props.onModel(e.target.value)}
        onBlur={props.onModelCommit}
      />
    </div>
  );
}

// Pick a place and a window of ticks from the CITY run, and get a SCENE
// Simulation node wired with whoever was there (background residents are
// promoted to saved characters first), starting at that place and time.
function ZoomIn({ nodeId, onZoomIn }: { nodeId: string; onZoomIn: (nodeId: string, result: CityZoomResult) => void }) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<CityZoomOptions | null>(null);
  const [place, setPlace] = useState('');
  const [from, setFrom] = useState(0);
  const [to, setTo] = useState(0);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    setMessage(null);
    try {
      const res = await agentsApi.cityZoomOptions();
      setOptions(res);
      setPlace(res.places[0]?.name ?? '');
      setFrom(0);
      setTo(Math.max(0, res.ticks - 1));
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  }

  async function create() {
    if (!place) return;
    setBusy(true);
    setMessage(null);
    try {
      const result = await agentsApi.cityZoom({ place, tickFrom: from, tickTo: Math.max(from, to), startedAt: options?.started_at });
      onZoomIn(nodeId, result);
      setMessage(
        `scene created: ${result.agent_names.length} people` +
          (result.promoted.length ? `, ${result.promoted.join(', ')} now saved characters` : ''),
      );
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <details
      className="node-subtitle"
      open={open}
      onToggle={(e) => {
        const isOpen = (e.target as HTMLDetailsElement).open;
        setOpen(isOpen);
        if (isOpen && !options) load();
      }}
    >
      <summary>zoom into a scene</summary>
      {options && options.places.length === 0 && <div>nobody was anywhere on the map</div>}
      {options && options.places.length > 0 && (
        <>
          <div className="node-controls">
            <select className="node-select" value={place} onChange={(e) => setPlace(e.target.value)}>
              {options.places.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name} ({p.heroes} heroes, {p.people} people)
                </option>
              ))}
            </select>
          </div>
          <div className="node-controls">
            <span>from</span>
            <select className="node-select" value={from} onChange={(e) => setFrom(Number(e.target.value))}>
              {options.times.map((t, i) => (
                <option key={i} value={i}>
                  {t}
                </option>
              ))}
            </select>
            <span>to</span>
            <select className="node-select" value={to} onChange={(e) => setTo(Number(e.target.value))}>
              {options.times.map((t, i) => (
                <option key={i} value={i} disabled={i < from}>
                  {t}
                </option>
              ))}
            </select>
          </div>
          <button className="node-run-btn" disabled={busy || !place} onClick={create}>
            {busy ? 'creating…' : '▶ create scene'}
          </button>
        </>
      )}
      {message && <div>{message}</div>}
    </details>
  );
}

const WAVE_ORDER = ['plan', 'decompose', 'encounters', 'react', 'dialogue', 'memory', 'reflect', 'promote'];

// The last tick at a glance: how long it took and where the time went
// (one bar segment per wave), how much was asked of the model, and how
// many calls each tier made per agent.
function Metrics({ m }: { m: CityMetrics }) {
  const total = WAVE_ORDER.reduce((s, w) => s + (m.waves[w] ?? 0), 0) || 1;
  const trouble = m.failures + m.retries + m.backpressure;
  return (
    <div className="city-metrics">
      <div className="city-metrics-head">
        <span>tick {m.tick + 1}{m.time ? ` · ${m.time}` : ''}</span>
        <span>{m.seconds.toFixed(1)} s</span>
      </div>
      <div className="city-waves" role="img" aria-label="time per wave">
        {WAVE_ORDER.filter((w) => (m.waves[w] ?? 0) > 0).map((w) => (
          <span
            key={w}
            className={`city-wave city-wave-${w}`}
            style={{ flexGrow: m.waves[w] / total }}
            title={`${w}: ${m.waves[w].toFixed(2)} s`}
          />
        ))}
      </div>
      <div className="city-metrics-grid">
        <span>{m.requests} requests</span>
        <span>{m.tokens_per_second} tok/s</span>
        <span>
          {m.calls_per_hero} / hero · {m.calls_per_background} / background
        </span>
        <span className={trouble ? 'city-metrics-bad' : ''}>
          {m.failures} failed · {m.retries} retries{m.backpressure ? ` · ${m.backpressure} backoffs` : ''}
        </span>
      </div>
    </div>
  );
}
