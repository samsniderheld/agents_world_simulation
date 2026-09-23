import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { visuals } from '../../api/client';
import { pollVisualsUntilDone } from '../../api/pollVisuals';
import { NodeShell } from './NodeShell';

export interface ScratchMusicNodeData extends Record<string, unknown> {
  prompt: string;
  negativePrompt: string;
  url?: string;
  onUpdate: (nodeId: string, patch: { prompt?: string; negativePrompt?: string; url?: string }) => void;
}

export type ScratchMusicNodeType = Node<ScratchMusicNodeData, 'scratch-music'>;

// Text-to-music (Google Lyria 2 via fal). No ports: nothing in this app
// consumes audio downstream of it.
export function ScratchMusicNode({ id, data, selected }: NodeProps<ScratchMusicNodeType>) {
  const [prompt, setPrompt] = useState(data.prompt);
  const [negativePrompt, setNegativePrompt] = useState(data.negativePrompt);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate() {
    setError(null);
    setPending(true);
    try {
      const start = await visuals.generateMusic({ prompt, negativePrompt: negativePrompt || undefined });
      if (!start.ok) {
        setError(start.error ?? 'failed to start');
        return;
      }
      const result = await pollVisualsUntilDone();
      if (result.kind !== 'music') {
        setError('generation finished with no audio');
        return;
      }
      data.onUpdate(id, { prompt, negativePrompt, url: result.audio.url });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <NodeShell typeLabel="Music" selected={selected} running={pending} error={Boolean(error)} wide>
      <textarea
        className="node-prompt-input"
        rows={2}
        value={prompt}
        placeholder="Describe the music…"
        onChange={(e) => setPrompt(e.target.value)}
        onBlur={() => prompt !== data.prompt && data.onUpdate(id, { prompt })}
      />
      <input
        className="node-select"
        value={negativePrompt}
        placeholder="negative prompt (optional)"
        onChange={(e) => setNegativePrompt(e.target.value)}
        onBlur={() => negativePrompt !== data.negativePrompt && data.onUpdate(id, { negativePrompt })}
      />
      {data.url && <audio controls src={visuals.fileUrl(data.url)} style={{ width: '100%' }} />}
      {error && <div className="node-error-text">{error}</div>}
      <div className="node-controls">
        <button className="node-run-btn" disabled={pending || !prompt.trim()} onClick={generate}>
          {pending ? 'generating…' : data.url ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>
    </NodeShell>
  );
}
