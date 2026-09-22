import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { visuals } from '../../api/client';
import { NodeShell } from './NodeShell';
import { Port } from './Port';
import { useVideoGeneration } from './useVideoGeneration';

export interface VideoNodeData extends Record<string, unknown> {
  // Resolved by the parent from the connected Frame node -- both stay
  // undefined until that Frame has generated something to connect.
  sourceImagePath?: string;
  sourceImageUrl?: string;
  // Resolved from a connected Style node the same way FrameNodeData's is.
  mergedStylePrompt?: string;
  prompt: string;
  // Self-contained, like FrameNode/ScratchImageNode -- a generated clip
  // belongs to this node/the treatment it's part of, not to any one
  // entity's media history.
  url?: string;
  localPath?: string;
  onUpdate: (nodeId: string, patch: { prompt?: string; url?: string; localPath?: string }) => void;
}

export type VideoNodeType = Node<VideoNodeData, 'video'>;

// Only makes sense once a Frame node has generated a real image to
// animate -- generate-video has no text-to-video path (verified against
// providers/base.py), so image:in is a required connection, not optional.
export function VideoNode({ id, data, selected }: NodeProps<VideoNodeType>) {
  const [prompt, setPrompt] = useState(data.prompt);
  const { pending, error, generate } = useVideoGeneration();

  async function onGenerate() {
    if (!data.sourceImagePath) return;
    const result = await generate(prompt, data.sourceImagePath, data.mergedStylePrompt);
    if (result) data.onUpdate(id, { prompt, url: result.url, localPath: result.localPath });
  }

  const noSource = !data.sourceImagePath;

  return (
    <NodeShell typeLabel="Video" selected={selected} running={pending} error={Boolean(error)} minWidth={540} minHeight={430}>
      <div className="node-media-box">
        {data.url ? (
          <video
            src={visuals.fileUrl(data.url)}
            muted
            loop
            onMouseEnter={(e) => e.currentTarget.play()}
            onMouseLeave={(e) => e.currentTarget.pause()}
          />
        ) : data.sourceImageUrl ? (
          <img src={data.sourceImageUrl} alt="" />
        ) : (
          <div className="node-media-box-empty">🎞️</div>
        )}
      </div>
      {noSource && <div className="node-subtitle">connect a generated Frame's image</div>}
      <textarea
        className="node-prompt-input"
        rows={2}
        value={prompt}
        placeholder="Describe the motion…"
        onChange={(e) => setPrompt(e.target.value)}
        onBlur={() => prompt !== data.prompt && data.onUpdate(id, { prompt })}
      />
      {error && <div className="node-error-text">{error}</div>}
      <div className="node-controls">
        <button className="node-run-btn" disabled={pending || noSource || !prompt.trim()} onClick={onGenerate}>
          {pending ? 'generating…' : data.url ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>

      <Port id="image:in" type="image" direction="in" label="image" top="calc(100% - 34px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional={!data.mergedStylePrompt} top="calc(100% - 14px)" />
      <Port id="video:out" type="video" direction="out" label="video" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
