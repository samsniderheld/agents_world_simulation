import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { agentsApi } from '../../api/client';
import type { Character } from '../../api/types';
import { useJobStore } from '../../state/jobStore';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface AgentNodeData extends Record<string, unknown> {
  character: Character;
  thumbUrl?: string;
  onExpand: (characterId: string) => void;
}

export type AgentNodeType = Node<AgentNodeData, 'agent'>;

export function AgentNode({ data, selected }: NodeProps<AgentNodeType>) {
  const { character, thumbUrl, onExpand } = data;
  const [ticks, setTicks] = useState(8);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const agentsState = useJobStore((s) => s.agentsState);

  const globallyRunning = agentsState?.status.phase === 'running';
  const thisRow = agentsState?.agents.find((a) => a.name === character.name);
  const thisRunning = globallyRunning && Boolean(thisRow);
  const initial = character.name.trim().charAt(0).toUpperCase() || '?';

  const stateLabel = thisRunning
    ? `running${thisRow ? ` · ${thisRow.location}` : ''}`
    : pending
      ? 'starting…'
      : error
        ? `error · ${error}`
        : 'idle';

  async function runSingle() {
    setError(null);
    setPending(true);
    try {
      const res = await agentsApi.run({ agentNames: [character.name], ticks });
      if (!res.ok) setError(res.error ?? 'failed to start');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <NodeShell typeLabel="Agent" selected={selected} running={thisRunning} error={Boolean(error)} onExpand={() => onExpand(character.id)}>
      <div className="node-thumb-row">
        <div className="node-thumb">{thumbUrl ? <img src={thumbUrl} alt="" /> : initial}</div>
        <div>
          <div className="node-title">{character.name}</div>
          <div className="node-subtitle">{character.occupation ?? character.quirk ?? 'resident'}</div>
        </div>
      </div>
      {character.place_name && <div className="node-grounding">@ {character.place_name}</div>}

      <div className={`node-state-row ${thisRunning ? 'is-running' : ''}`}>
        <span className="node-state-dot" />
        {stateLabel}
      </div>

      <div className="node-controls">
        <input
          className="node-ticks-input"
          type="number"
          min={1}
          max={50}
          value={ticks}
          onChange={(e) => setTicks(Number(e.target.value) || 1)}
        />
        <button className="node-run-btn" disabled={globallyRunning || pending} onClick={runSingle}>
          {thisRunning ? 'running' : '▶ run'}
        </button>
      </div>

      <Port id="agent:out" type="agent" direction="out" label="agent" top="calc(100% - 34px)" />
      <Port id="run:out" type="run" direction="out" label="run" top="calc(100% - 14px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional top="calc(100% - 14px)" />
    </NodeShell>
  );
}
