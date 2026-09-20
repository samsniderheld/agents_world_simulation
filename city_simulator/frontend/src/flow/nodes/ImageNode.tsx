import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { city } from '../../api/client';
import { NodeShell } from './NodeShell';
import { Port } from './Port';
import { useImageGeneration } from './useImageGeneration';

export interface ImageNodeData extends Record<string, unknown> {
  entityId: string;
  prompt: string;
  mediaId?: string;
  mediaUrl?: string;
  onUpdate: (nodeId: string, patch: { prompt?: string; mediaId?: string; mediaUrl?: string }) => void;
}

export type ImageNodeType = Node<ImageNodeData, 'image'>;

// Standalone per-entity image generation -- the node-ified version of the
// old app's "+ Media" button. Not part of the Simulation/Treatment/Frame
// pipeline (that's FrameNode, which shares this same generation logic
// but requires a `shot:in` connection) -- this one's prompt is entirely
// free-form.
export function ImageNode({ id, data, selected }: NodeProps<ImageNodeType>) {
  const [prompt, setPrompt] = useState(data.prompt);
  const { pending, error, generate } = useImageGeneration(data.entityId);

  async function onGenerate() {
    const media = await generate(prompt);
    if (media) data.onUpdate(id, { prompt, mediaId: media.id, mediaUrl: city.fileUrl(media.url) });
  }

  return (
    <NodeShell typeLabel="Image" selected={selected} running={pending} error={Boolean(error)}>
      <div className="node-thumb-row">
        <div className="node-thumb" style={{ width: 64, height: 64 }}>
          {data.mediaUrl ? <img src={data.mediaUrl} alt="" /> : '🖼'}
        </div>
      </div>
      <textarea
        className="node-prompt-input"
        rows={3}
        value={prompt}
        placeholder="Describe the image…"
        onChange={(e) => setPrompt(e.target.value)}
        onBlur={() => prompt !== data.prompt && data.onUpdate(id, { prompt })}
      />
      {error && <div className="node-error-text">{error}</div>}
      <div className="node-controls">
        <button className="node-run-btn" disabled={pending || !prompt.trim()} onClick={onGenerate}>
          {pending ? 'generating…' : data.mediaId ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>

      <Port id="shot:in" type="shot" direction="in" label="shot" optional top="calc(100% - 34px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional top="calc(100% - 14px)" />
      <Port id="image:out" type="image" direction="out" label="image" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
