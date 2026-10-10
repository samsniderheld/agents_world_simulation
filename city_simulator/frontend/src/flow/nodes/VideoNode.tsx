import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { visuals } from '../../api/client';
import { AspectSelect, type AspectRatio } from './AspectSelect';
import { NodeShell } from './NodeShell';
import { Port } from './Port';
import { ComfyServerField } from './ComfyServerField';
import { ProviderSelect } from './ProviderSelect';
import { useVisualsProviders } from './useProviderCapabilities';
import { useVideoGeneration } from './useVideoGeneration';
import { VideoOptions, type VideoOptionValues } from './VideoOptions';

export interface VideoNodeData extends Record<string, unknown> {
  // Resolved by the parent from the connected Frame node -- both stay
  // undefined until that Frame has generated something to connect.
  sourceImagePath?: string;
  sourceImageUrl?: string;
  // Resolved from a connected Style node the same way FrameNodeData's is.
  mergedStylePrompt?: string;
  // Whether style:in actually has an edge -- independent of
  // mergedStylePrompt, so the port still shows "connected" even when the
  // linked Style has no prompt text (reference images only, or blank).
  hasStyleRef?: boolean;
  aspectRatio?: AspectRatio;
  // Which service animates it ("fal" | "comfyui"); blank = the server's
  // default for video.
  provider?: string;
  // ComfyUI only: the workflow's options (VideoOptions.tsx), and the seed the
  // last clip was made with.
  options?: VideoOptionValues;
  lastSeed?: number;
  comfyuiUrl?: string; // this node's own ComfyUI address (blank = the default)
  prompt: string;
  // Self-contained, like an Image node's own result -- a generated clip
  // belongs to this node/the treatment it's part of, not to any one
  // entity's media history.
  url?: string;
  localPath?: string;
  onUpdate: (
    nodeId: string,
    patch: { prompt?: string; aspectRatio?: AspectRatio; provider?: string; options?: VideoOptionValues; lastSeed?: number; comfyuiUrl?: string; url?: string; localPath?: string },
  ) => void;
}

export type VideoNodeType = Node<VideoNodeData, 'video'>;

// Only makes sense once a Frame node has generated a real image to
// animate -- generate-video has no text-to-video path (verified against
// providers/base.py), so image:in is a required connection, not optional.
export function VideoNode({ id, data, selected }: NodeProps<VideoNodeType>) {
  const [prompt, setPrompt] = useState(data.prompt);
  const { pending, error, generate } = useVideoGeneration();
  const providers = useVisualsProviders();
  const comfy = (data.provider || providers?.defaults.video) === 'comfyui';

  async function onGenerate() {
    if (!data.sourceImagePath) return;
    const result = await generate(prompt, data.sourceImagePath, data.mergedStylePrompt, data.aspectRatio ?? '16:9', data.provider,
      comfy ? { ...(data.options ?? {}) } : {}, data.comfyuiUrl);
    if (result) data.onUpdate(id, { prompt, url: result.url, localPath: result.localPath, lastSeed: result.seed });
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
      {comfy && (
        <ComfyServerField kind="video" value={data.comfyuiUrl ?? ''} info={providers}
          onChange={(url) => data.onUpdate(id, { comfyuiUrl: url || undefined })} />
      )}
      {comfy && (
        <VideoOptions value={data.options ?? {}} lastSeed={data.lastSeed} onChange={(options) => data.onUpdate(id, { options })} />
      )}
      {error && <div className="node-error-text">{error}</div>}
      <div className="node-controls">
        <AspectSelect value={data.aspectRatio ?? '16:9'} onChange={(v) => data.onUpdate(id, { aspectRatio: v })} />
        <ProviderSelect kind="video" value={data.provider ?? ''} info={providers} onChange={(v) => data.onUpdate(id, { provider: v || undefined })} />
        <button className="node-run-btn" disabled={pending || noSource || !prompt.trim()} onClick={onGenerate}>
          {pending ? 'generating…' : data.url ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>

      <Port id="image:in" type="image" direction="in" label="image" top="calc(100% - 34px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional={!data.hasStyleRef} top="calc(100% - 14px)" />
      <Port id="video:out" type="video" direction="out" label="video" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
