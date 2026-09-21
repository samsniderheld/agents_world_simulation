import { useEffect, useRef, useState } from 'react';
import type { UIEvent } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { agentsApi } from '../../api/client';
import type { AgentEvent } from '../../api/types';
import { eventLine } from '../../inspector/format';
import { useJobStore } from '../../state/jobStore';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface SimulationNodeData extends Record<string, unknown> {
  ticks: number;
  // Free-text scene guidance -- "guide how the characters are
  // interacting" -- forwarded verbatim to agents/routes.py's /run and
  // from there into every plan/decompose/react/dialogue call this run
  // makes (see agents/textutil.directive_block).
  directive: string;
  // "ollama" (local) or "claude" (API) -- agents/providers/__init__.py's
  // AVAILABLE_PROVIDERS. chatModel overrides that provider's default
  // model (blank = server default, e.g. config.CHAT_MODEL/CLAUDE_MODEL).
  // Embeddings always use Ollama regardless of this choice (agents/
  // llm.py's docstring), so switching to Claude doesn't need Ollama gone.
  provider: string;
  chatModel: string;
  // Log display filter, not a run param -- true (default) shows every
  // event kind exactly as before; false narrows the log to just action/
  // dialogue lines, dropping plan/decompose/observe/react/continue/
  // memory/reflect_pause/move noise. Unrelated to simulation.run()'s own
  // `verbose` flag, which only controls server-terminal printing and
  // this node never sends.
  verbose: boolean;
  // Resolved by the parent canvas from connected Agent/Location nodes'
  // edges -- this node has no idea what's wired to it, only who it is.
  agentNames: string[];
  placeId?: string;
  placeName?: string;
  onTicksChange: (nodeId: string, ticks: number) => void;
  onDirectiveChange: (nodeId: string, directive: string) => void;
  onProviderChange: (nodeId: string, provider: string) => void;
  onChatModelChange: (nodeId: string, chatModel: string) => void;
  onVerboseChange: (nodeId: string, verbose: boolean) => void;
}

export type SimulationNodeType = Node<SimulationNodeData, 'sim'>;

export function SimulationNode({ id, data, selected, height }: NodeProps<SimulationNodeType>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [directive, setDirective] = useState(data.directive);
  const [chatModel, setChatModel] = useState(data.chatModel);
  const [models, setModels] = useState<string[]>([]);
  const [recent, setRecent] = useState<AgentEvent[]>([]);
  const sinceRef = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);
  // Only auto-follows new lines while already scrolled to (or near) the
  // bottom -- otherwise a poll landing mid-review would keep yanking a
  // user who scrolled up back down to the latest line.
  const stickToBottomRef = useRef(true);
  const agentsState = useJobStore((s) => s.agentsState);

  // Identifies "is the currently-running (or just-finished) job actually
  // this node's" by exact participant-name match -- there's no run id in
  // the backend to key off (agents/jobs.py is one global slot), so this
  // is the same trick AgentNode uses for its own single-agent run state.
  const isOurs =
    data.agentNames.length > 0 &&
    Boolean(agentsState) &&
    agentsState!.agents.length === data.agentNames.length &&
    data.agentNames.every((n) => agentsState!.agents.some((a) => a.name === n));
  const globallyRunning = agentsState?.status.phase === 'running';
  const running = isOurs && globallyRunning;

  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    const poll = () =>
      agentsApi.events(sinceRef.current).then((res) => {
        if (cancelled) return;
        sinceRef.current = res.next;
        // Kept in full (not capped) -- the log area scrolls instead of
        // discarding older lines, so the whole run's output is still
        // there to review after it finishes, not just the last few.
        setRecent((prev) => [...prev, ...(res.events as AgentEvent[])]);
      });
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [running]);

  const visibleEvents = data.verbose ? recent : recent.filter((e) => e.kind === 'action' || e.kind === 'dialogue');

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visibleEvents]);

  // Ollama/Claude have entirely different model lists, so this re-fetches
  // whenever the provider changes -- same trigger the old app's Provider
  // <select> used for its model <datalist> (static/js/agents.js).
  useEffect(() => {
    let cancelled = false;
    agentsApi
      .models(data.provider)
      .then((res) => {
        if (!cancelled) setModels(res.models);
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      });
    return () => {
      cancelled = true;
    };
  }, [data.provider]);

  function onProviderChange(nextProvider: string) {
    data.onProviderChange(id, nextProvider);
    // A model name typed for one provider is meaningless for the other
    // (e.g. an Ollama tag vs a Claude model id) -- cleared the same way
    // the old app's provider <select> cleared its model field on change.
    setChatModel('');
    data.onChatModelChange(id, '');
  }

  function onLogScroll(e: UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    stickToBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  }

  async function run() {
    setError(null);
    setPending(true);
    setRecent([]);
    sinceRef.current = 0;
    try {
      const res = await agentsApi.run({
        agentNames: data.agentNames,
        ticks: data.ticks,
        placeId: data.placeId,
        locationMode: data.placeId ? 'convene' : 'grounded',
        // Local state, not data.directive/data.chatModel -- reads
        // whatever's currently typed even if the field hasn't blurred
        // (and thus persisted) yet, the same way ImageNode's Generate
        // reads its local prompt state rather than waiting on a round
        // trip through node data.
        directive,
        provider: data.provider || undefined,
        chatModel: chatModel.trim() || undefined,
      });
      if (!res.ok) setError(res.error ?? 'failed to start');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  const noAgents = data.agentNames.length === 0;

  return (
    <NodeShell typeLabel="Simulation" selected={selected} running={running} error={Boolean(error)} wide>
      <div className="node-title">Simulation</div>
      <div className="node-grounding">
        {noAgents ? 'connect agent nodes' : `${data.agentNames.length} agent${data.agentNames.length === 1 ? '' : 's'} connected`}
      </div>
      <div className="node-grounding">{data.placeName ? `convene: ${data.placeName}` : 'grounded (each at their own place)'}</div>

      <textarea
        className="node-prompt-input"
        rows={2}
        value={directive}
        placeholder={`Guide how they interact, e.g. "they're arguing about the missing shipment"…`}
        onChange={(e) => setDirective(e.target.value)}
        onBlur={() => directive !== data.directive && data.onDirectiveChange(id, directive)}
      />

      <div className="node-controls">
        <select className="node-select" value={data.provider} onChange={(e) => onProviderChange(e.target.value)}>
          <option value="ollama">Ollama (local)</option>
          <option value="claude">Claude (API)</option>
        </select>
      </div>
      <div className="node-controls">
        <input
          className="node-select"
          list={`sim-models-${id}`}
          placeholder="model (server default)"
          value={chatModel}
          onChange={(e) => setChatModel(e.target.value)}
          onBlur={() => chatModel !== data.chatModel && data.onChatModelChange(id, chatModel)}
        />
        <datalist id={`sim-models-${id}`}>
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </div>
      <div className="node-subtitle">Claude still uses local Ollama for memory embeddings.</div>

      <div className="node-controls">
        <span className="node-subtitle">ticks</span>
        <input
          className="node-ticks-input"
          type="number"
          min={1}
          max={50}
          value={data.ticks}
          onChange={(e) => data.onTicksChange(id, Number(e.target.value) || 1)}
        />
        <button className="node-run-btn" disabled={noAgents || globallyRunning || pending} onClick={run}>
          {running ? 'running…' : '▶ run'}
        </button>
      </div>
      <label className="node-checkbox-row">
        <input type="checkbox" checked={data.verbose} onChange={(e) => data.onVerboseChange(id, e.target.checked)} />
        <span className="node-subtitle">verbose (unchecked: actions &amp; dialogue only)</span>
      </label>

      {error && <div className="node-error-text">{error}</div>}

      {visibleEvents.length > 0 && (
        // Capped at a fixed height by default so a long run scrolls
        // inside a stable box rather than growing the node without
        // bound; once the node's been drag-resized (height is then
        // explicit, see NodeShell's NodeResizer), the cap is lifted so
        // the log actually uses the extra room instead of leaving it
        // blank under a still-240px box.
        <div className="node-log" ref={logRef} onScroll={onLogScroll} style={{ maxHeight: height ? undefined : 240 }}>
          {visibleEvents.map((e, i) => (
            <div className="node-log-row" key={i}>
              <span className="node-log-badge">{e.kind}</span>
              {e.agent && <span>{e.agent}: </span>}
              {eventLine(e)}
            </div>
          ))}
        </div>
      )}

      <Port id="agents:in" type="agent" direction="in" label="agents" top="calc(100% - 34px)" />
      <Port id="place:in" type="place" direction="in" label="place" optional={!data.placeName} top="calc(100% - 14px)" />
      <Port id="run:out" type="run" direction="out" label="run" top="calc(100% - 24px)" />
    </NodeShell>
  );
}
