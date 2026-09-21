import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { city } from '../../api/client';
import { useLightboxStore } from '../../state/lightboxStore';
import { NodeShell } from './NodeShell';
import { Port } from './Port';
import { useImageGeneration } from './useImageGeneration';

export interface ImageNodeData extends Record<string, unknown> {
  entityId: string;
  prompt: string;
  mediaId?: string;
  mediaUrl?: string;
  // Resolved by pipeline.ts's enrichPipelineNodes() from any connected
  // Style node(s) -- merged (prompts joined with ", ", reference arrays
  // concatenated) since more than one can feed this port.
  mergedStylePrompt?: string;
  mergedStyleReferenceImages?: string[];
  // Resolved by pipeline.ts's enrichPipelineNodes() from any Agent/
  // Location connected to this node's agent:in/place:in ports -- their
  // own generated images, used as reference images the same way a
  // Style's reference_images are (both end up in the same image_paths
  // list server-side, per visuals/routes.py's _style_reference_images()).
  mergedEntityReferenceImages?: string[];
  // Whether agent:in/place:in each actually have an edge -- independent of
  // mergedEntityReferenceImages, so the port still shows "connected" even
  // when the linked Agent/Location has no photos yet.
  hasAgentRef?: boolean;
  hasPlaceRef?: boolean;
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
  const openLightbox = useLightboxStore((s) => s.open);

  async function onGenerate() {
    const media = await generate(prompt, '', {
      stylePrompt: data.mergedStylePrompt,
      styleReferenceImages: [...(data.mergedStyleReferenceImages ?? []), ...(data.mergedEntityReferenceImages ?? [])],
    });
    if (media) data.onUpdate(id, { prompt, mediaId: media.id, mediaUrl: city.fileUrl(media.url) });
  }

  return (
    <NodeShell typeLabel="Image" selected={selected} running={pending} error={Boolean(error)} minWidth={540} minHeight={430}>
      <div
        className={`node-media-box ${data.mediaUrl ? 'is-expandable' : ''}`}
        onClick={(e) => {
          if (!data.mediaUrl) return;
          e.stopPropagation();
          openLightbox(data.mediaUrl);
        }}
      >
        {data.mediaUrl ? <img src={data.mediaUrl} alt="" /> : <div className="node-media-box-empty">🖼</div>}
      </div>
      <textarea
        className="node-prompt-input"
        rows={3}
        value={prompt}
        placeholder="Describe the image…"
        onChange={(e) => setPrompt(e.target.value)}
        onBlur={() => prompt !== data.prompt && data.onUpdate(id, { prompt })}
      />
      {data.mergedStylePrompt && <div className="node-subtitle">style: {data.mergedStylePrompt}</div>}
      {error && <div className="node-error-text">{error}</div>}
      <div className="node-controls">
        <button className="node-run-btn" disabled={pending || !prompt.trim()} onClick={onGenerate}>
          {pending ? 'generating…' : data.mediaId ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>

      <Port id="agent:in" type="agent" direction="in" label="agent" optional={!data.hasAgentRef} top="calc(100% - 74px)" />
      <Port id="place:in" type="place" direction="in" label="place" optional={!data.hasPlaceRef} top="calc(100% - 54px)" />
      <Port id="shot:in" type="shot" direction="in" label="shot" optional top="calc(100% - 34px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional={!data.mergedStylePrompt} top="calc(100% - 14px)" />
      <Port id="image:out" type="image" direction="out" label="image" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
