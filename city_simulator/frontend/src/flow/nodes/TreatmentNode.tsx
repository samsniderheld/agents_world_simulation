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
  // Independent of whatever provider/model actually ran the simulation --
  // agents/routes.py's POST /treatment takes its own provider/model
  // overrides (blank = server default), same shape as SimulationNode's.
  provider: string;
  model: string;
  onSubjectChange: (nodeId: string, subjectId: string) => void;
  onGenerated: (nodeId: string, text: string, shots: string[]) => void;
  onEmitFrames: (nodeId: string, shots: string[]) => void;
  onProviderChange: (nodeId: string, provider: string) => void;
  onModelChange: (nodeId: string, model: string) => void;
}

export type TreatmentNodeType = Node<TreatmentNodeData, 'treatment'>;

export function TreatmentNode({ id, data, selected }: NodeProps<TreatmentNodeType>) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [model, setModel] = useState(data.model);
  const [models, setModels] = useState<string[]>([]);
  const { candidates, subjectId, text, shots, onSubjectChange, onGenerated, onEmitFrames } = data;

  // Ollama/Claude have entirely different model lists -- re-fetches
  // whenever the provider changes, same as SimulationNode's.
  useEffect(() => {
    let cancelled = false;
    agentsApi
      .models(data.provider || undefined)
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
    // A model name typed for one provider means nothing to the other.
    setModel('');
    data.onModelChange(id, '');
  }

  // No manual picker -- agents/treatment.py's build_transcript() already
  // merges every co-participant of the same run into one shared
  // transcript keyed by started_at, so which candidate's id is used only
  // decides "which agent's own file does this get filed under," not what
  // the treatment is about. First candidate is just as good as any other
  // here; this re-syncs whenever the connected run's candidates change
  // (e.g. wiring a different Simulation in), not just on first connect.
  useEffect(() => {
    const nextId = candidates[0]?.id;
    if (nextId && nextId !== subjectId) onSubjectChange(id, nextId);
  }, [candidates, subjectId, id, onSubjectChange]);

  async function generate() {
    if (!subjectId) return;
    setError(null);
    setPending(true);
    try {
      const res = await agentsApi.generateTreatment(subjectId, {
        provider: data.provider || undefined,
        model: model.trim() || undefined,
      });
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
      {candidates.length === 1 && <div className="node-grounding">for {candidates[0].name}</div>}
      {candidates.length > 1 && (
        <div className="node-grounding">based on the run: {candidates.map((c) => c.name).join(', ')}</div>
      )}

      {text && (
        <div className="node-treatment-preview">
          {text.split('\n').slice(0, 2).join(' ')}
          {shots && shots.length > 0 && <div className="node-subtitle">{shots.length} shots</div>}
        </div>
      )}

      <div className="node-controls">
        <select className="node-select" value={data.provider} onChange={(e) => onProviderChange(e.target.value)}>
          <option value="">Server default</option>
          <option value="ollama">Ollama (local)</option>
          <option value="claude">Claude (API)</option>
        </select>
      </div>
      <div className="node-controls">
        <input
          className="node-select"
          list={`treatment-models-${id}`}
          placeholder="model (server default)"
          value={model}
          onChange={(e) => setModel(e.target.value)}
          onBlur={() => model !== data.model && data.onModelChange(id, model)}
        />
        <datalist id={`treatment-models-${id}`}>
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </div>

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
