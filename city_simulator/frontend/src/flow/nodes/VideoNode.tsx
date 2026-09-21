import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { city } from '../../api/client';
import { NodeShell } from './NodeShell';
import { Port } from './Port';
import { useVideoGeneration } from './useVideoGeneration';

export interface VideoNodeData extends Record<string, unknown> {
  // Both resolved by the parent from the connected Frame node -- a Video
  // node has no entity of its own; it attaches its result to whichever
  // agent/place the upstream Frame belongs to. sourceImagePath is the
  // Frame's real local_path (generate-video needs a filesystem path, not
  // just a URL); both stay undefined until that Frame has generated
  // something to connect.
  entityId?: string;
  sourceImagePath?: string;
  sourceImageUrl?: string;
  // Resolved from a connected Style node the same way FrameNodeData's is.
  mergedStylePrompt?: string;
  prompt: string;
  mediaId?: string;
  mediaUrl?: string;
  onUpdate: (nodeId: string, patch: { prompt?: string; mediaId?: string; mediaUrl?: string }) => void;
}

export type VideoNodeType = Node<VideoNodeData, 'video'>;

// Only makes sense once a Frame node has generated a real image to
// animate -- generate-video has no text-to-video path (verified against
// providers/base.py), so image:in is a required connection, not optional.
export function VideoNode({ id, data, selected }: NodeProps<VideoNodeType>) {
  const [prompt, setPrompt] = useState(data.prompt);
  const { pending, error, generate } = useVideoGeneration(data.entityId ?? '');

  async function onGenerate() {
    if (!data.sourceImagePath || !data.entityId) return;
    const media = await generate(prompt, data.sourceImagePath, data.mergedStylePrompt);
    if (media) data.onUpdate(id, { prompt, mediaId: media.id, mediaUrl: city.fileUrl(media.url) });
  }

  const noSource = !data.sourceImagePath || !data.entityId;

  return (
    <NodeShell typeLabel="Video" selected={selected} running={pending} error={Boolean(error)} minWidth={540} minHeight={430}>
      <div className="node-media-box">
        {data.mediaUrl ? (
          <video src={data.mediaUrl} muted loop onMouseEnter={(e) => e.currentTarget.play()} onMouseLeave={(e) => e.currentTarget.pause()} />
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
          {pending ? 'generating…' : data.mediaId ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>

      <Port id="image:in" type="image" direction="in" label="image" top="calc(100% - 34px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional={!data.mergedStylePrompt} top="calc(100% - 14px)" />
      <Port id="video:out" type="video" direction="out" label="video" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
