import { useEffect, useRef, useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { agentsApi } from '../../api/client';
import type { AgentEvent } from '../../api/types';
import { eventLine } from '../../inspector/format';
import { useJobStore } from '../../state/jobStore';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface SimulationNodeData extends Record<string, unknown> {
  ticks: number;
  // Resolved by the parent canvas from connected Agent/Location nodes'
  // edges -- this node has no idea what's wired to it, only who it is.
  agentNames: string[];
  placeId?: string;
  placeName?: string;
  onTicksChange: (nodeId: string, ticks: number) => void;
}

export type SimulationNodeType = Node<SimulationNodeData, 'sim'>;

export function SimulationNode({ id, data, selected }: NodeProps<SimulationNodeType>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recent, setRecent] = useState<AgentEvent[]>([]);
  const sinceRef = useRef(0);
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
        setRecent((prev) => [...prev, ...(res.events as AgentEvent[])].slice(-8));
      });
    poll();
    const timer = setInterval(poll, 1500);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [running]);

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

      {error && <div className="node-error-text">{error}</div>}

      {recent.length > 0 && (
        <div className="node-log">
          {recent.map((e, i) => (
            <div className="node-log-row" key={i}>
              <span className="node-log-badge">{e.kind}</span>
              {e.agent && <span>{e.agent}: </span>}
              {eventLine(e)}
            </div>
          ))}
        </div>
      )}

      <Port id="agents:in" type="agent" direction="in" label="agents" top="calc(100% - 34px)" />
      <Port id="place:in" type="place" direction="in" label="place" optional top="calc(100% - 14px)" />
      <Port id="run:out" type="run" direction="out" label="run" top="calc(100% - 24px)" />
    </NodeShell>
  );
}
