import { useEffect, useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { agentsApi } from '../../api/client';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface TreatmentCandidate {
  id: string;
  name: string;
}

export interface TreatmentNodeData extends Record<string, unknown> {
  // Resolved by the parent from whatever's wired into run:in (an Agent's
  // own run:out, or a Simulation's) -- who this treatment could be
  // generated for. There's no run-id in the backend to target a specific
  // historical run (POST /api/agents/treatment always uses that agent's
  // *most recent* run), so "connected" really just means "eligible
  // subject," not a specific run's data flowing through the wire.
  candidates: TreatmentCandidate[];
  subjectId?: string;
  text?: string;
  shots?: string[];
  onSubjectChange: (nodeId: string, subjectId: string) => void;
  onGenerated: (nodeId: string, text: string, shots: string[]) => void;
  onEmitFrames: (nodeId: string, shots: string[]) => void;
}

export type TreatmentNodeType = Node<TreatmentNodeData, 'treatment'>;

export function TreatmentNode({ id, data, selected }: NodeProps<TreatmentNodeType>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { candidates, subjectId, text, shots, onSubjectChange, onGenerated, onEmitFrames } = data;

  // Auto-pick the one candidate when there's exactly one (the common
  // single-agent-run case); multiple candidates (a multi-agent
  // Simulation) need an explicit choice, same as the old Director tab's
  // Character dropdown.
  useEffect(() => {
    if (!subjectId && candidates.length === 1) onSubjectChange(id, candidates[0].id);
  }, [subjectId, candidates, id, onSubjectChange]);

  async function generate() {
    if (!subjectId) return;
    setError(null);
    setPending(true);
    try {
      const res = await agentsApi.generateTreatment(subjectId);
      const shotsRes = await agentsApi.treatmentShots(res.treatment.text);
      onGenerated(id, res.treatment.text, shotsRes.shots);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <NodeShell typeLabel="Treatment" selected={selected} running={pending} error={Boolean(error)} wide>
      {candidates.length === 0 && <div className="node-subtitle">connect a run (Agent or Simulation)</div>}
      {candidates.length > 1 && (
        <select className="node-select" value={subjectId ?? ''} onChange={(e) => onSubjectChange(id, e.target.value)}>
          <option value="" disabled>
            pick a subject…
          </option>
          {candidates.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      )}
      {candidates.length === 1 && <div className="node-grounding">for {candidates[0].name}</div>}

      {text && (
        <div className="node-treatment-preview">
          {text.split('\n').slice(0, 2).join(' ')}
          {shots && shots.length > 0 && <div className="node-subtitle">{shots.length} shots</div>}
        </div>
      )}

      {error && <div className="node-error-text">{error}</div>}

      <div className="node-controls">
        <button className="node-run-btn" disabled={!subjectId || pending} onClick={generate}>
          {pending ? 'generating…' : text ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>
      {shots && shots.length > 0 && (
        <div className="node-controls">
          <button className="node-run-btn" onClick={() => onEmitFrames(id, shots)}>
            emit {shots.length} frames
          </button>
        </div>
      )}

      <Port id="run:in" type="run" direction="in" label="run" top="calc(100% - 44px)" />
      <Port id="treatment:out" type="treatment" direction="out" label="treatment" top="calc(100% - 24px)" />
      <Port id="shots:out" type="shot" direction="out" label="shots" top="calc(100% - 4px)" />
    </NodeShell>
  );
}
