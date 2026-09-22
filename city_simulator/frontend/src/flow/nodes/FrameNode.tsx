import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { visuals } from '../../api/client';
import { pollVisualsUntilDone } from '../../api/pollVisuals';
import { useLightboxStore } from '../../state/lightboxStore';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface FrameNodeData extends Record<string, unknown> {
  shotIndex: number;
  prompt: string;
  // Self-contained, like ScratchImageNode -- a storyboard shot's image
  // belongs to this node/the treatment it's part of, not to any one
  // character's or place's own media history. Entity-attaching it (the
  // original design, ported from the old Director tab) meant a two-agent
  // scene's shots only ever got filed under whichever one agent happened
  // to be the Treatment's chosen subject, and a place-only scene had
  // nowhere to attach to at all.
  url?: string;
  localPath?: string;
  // Resolved by pipeline.ts's enrichPipelineNodes() from any connected
  // Style node(s) -- merged (per the design's rule: prompts joined with
  // ", ", reference arrays concatenated) since more than one can feed
  // this port.
  mergedStylePrompt?: string;
  mergedStyleReferenceImages?: string[];
  // Resolved by pipeline.ts's enrichPipelineNodes() from any Agent/
  // Location connected to this node's agent:in/place:in ports -- their
  // own generated images, used as reference images the same way a
  // Style's reference_images are (both end up in the same image_paths
  // list server-side, per visuals/routes.py's _style_reference_images()).
  mergedEntityReferenceImages?: string[];
  // Whether agent:in/place:in/style:in each actually have an edge --
  // independent of mergedEntityReferenceImages/mergedStylePrompt, so the
  // port still shows "connected" even when the linked Agent/Location has
  // no photos yet, or the linked Style has no prompt text (reference
  // images only, or just created and still blank).
  hasAgentRef?: boolean;
  hasPlaceRef?: boolean;
  hasStyleRef?: boolean;
  onUpdate: (nodeId: string, patch: { prompt?: string; url?: string; localPath?: string }) => void;
}

export type FrameNodeType = Node<FrameNodeData, 'frame'>;

// A storyboard shot -- spawned by a Treatment node's "emit frames" action
// (pre-filled with that shot's parsed prompt and already wired via a
// shot:in edge), or dropped freely on any canvas like every other node
// type. No entity of its own to require or gate on.
export function FrameNode({ id, data, selected }: NodeProps<FrameNodeType>) {
  const [prompt, setPrompt] = useState(data.prompt);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const openLightbox = useLightboxStore((s) => s.open);

  async function onGenerate() {
    setError(null);
    setPending(true);
    try {
      const start = await visuals.generateImage({
        prompt,
        stylePrompt: data.mergedStylePrompt,
        styleReferenceImages: [...(data.mergedStyleReferenceImages ?? []), ...(data.mergedEntityReferenceImages ?? [])],
      });
      if (!start.ok) {
        setError(start.error ?? 'failed to start');
        return;
      }
      const result = await pollVisualsUntilDone();
      if (result.kind !== 'image' || !result.images[0]) {
        setError('generation finished with no image');
        return;
      }
      const image = result.images[0];
      data.onUpdate(id, { prompt, url: image.url, localPath: image.local_path });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <NodeShell
      typeLabel={`Frame ${String(data.shotIndex + 1).padStart(2, '0')}`}
      selected={selected}
      running={pending}
      error={Boolean(error)}
      minWidth={540}
      minHeight={430}
    >
      <div
        className={`node-media-box ${data.url ? 'is-expandable' : ''}`}
        onClick={(e) => {
          if (!data.url) return;
          e.stopPropagation();
          openLightbox(visuals.fileUrl(data.url));
        }}
      >
        {data.url ? <img src={visuals.fileUrl(data.url)} alt="" /> : <div className="node-media-box-empty">🎬</div>}
      </div>
      <textarea
        className="node-prompt-input"
        rows={3}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        onBlur={() => prompt !== data.prompt && data.onUpdate(id, { prompt })}
      />
      {data.mergedStylePrompt && <div className="node-subtitle">style: {data.mergedStylePrompt}</div>}
      {error && <div className="node-error-text">{error}</div>}
      <div className="node-controls">
        <button className="node-run-btn" disabled={pending || !prompt.trim()} onClick={onGenerate}>
          {pending ? 'generating…' : data.url ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>

      <Port id="agent:in" type="agent" direction="in" label="agent" optional={!data.hasAgentRef} top="calc(100% - 74px)" />
      <Port id="place:in" type="place" direction="in" label="place" optional={!data.hasPlaceRef} top="calc(100% - 54px)" />
      <Port id="shot:in" type="shot" direction="in" label="shot" optional top="calc(100% - 34px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional={!data.hasStyleRef} top="calc(100% - 14px)" />
      <Port id="image:out" type="image" direction="out" label="image" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
