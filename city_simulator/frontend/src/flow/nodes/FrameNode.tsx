import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { visuals } from '../../api/client';
import { pollVisualsUntilDone } from '../../api/pollVisuals';
import { useLightboxStore } from '../../state/lightboxStore';
import { NodeShell } from './NodeShell';
import { Port } from './Port';
import { useProviderCapabilities } from './useProviderCapabilities';

export interface FrameNodeData extends Record<string, unknown> {
  shotIndex: number;
  prompt: string;
  // Self-contained, like ScratchImageNode -- a storyboard shot's image
  // belongs to this node/the treatment it's part of, not to any one
  // character's or place's own media history. Entity-attaching it (the
  // original design) meant a two-agent scene's shots only ever got filed
  // under whichever one agent happened to be the Treatment's chosen
  // subject, and a place-only scene had nowhere to attach to at all.
  url?: string;
  localPath?: string;
  // The second prompt box: an instruction applied to the *current* image
  // ("make it night, add rain") rather than a fresh generation. Persisted
  // so it survives a reload like the main prompt does.
  editPrompt?: string;
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
  // Resolved by pipeline.ts from whatever's wired into image:in (another
  // Frame, or an Image node) -- sent with both generate and edit, first in
  // line ahead of the style/agent/place references.
  inputImagePaths?: string[];
  hasImageRef?: boolean;
  onUpdate: (nodeId: string, patch: { prompt?: string; editPrompt?: string; url?: string; localPath?: string }) => void;
}

export type FrameNodeType = Node<FrameNodeData, 'frame'>;

// A storyboard shot -- seeded inside a Storyboard's own canvas by a
// Treatment node's "create storyboard" action (pre-filled with that shot's
// parsed prompt and already wired to the carried-through Agent/Location/
// Style nodes), or dropped freely on any canvas like every other node
// type. No entity of its own to require or gate on.
export function FrameNode({ id, data, selected }: NodeProps<FrameNodeType>) {
  const [prompt, setPrompt] = useState(data.prompt);
  const [editPrompt, setEditPrompt] = useState(data.editPrompt ?? '');
  const [pending, setPending] = useState<'generate' | 'edit' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const openLightbox = useLightboxStore((s) => s.open);
  // The local provider is text-to-image only -- it can't take an input
  // image, so editing is greyed out rather than failing at submit time.
  const capabilities = useProviderCapabilities();
  const canEdit = capabilities?.supports_reference_images !== false;

  async function run(kind: 'generate' | 'edit', params: Parameters<typeof visuals.generateImage>[0], patch: { prompt?: string; editPrompt?: string }) {
    setError(null);
    setPending(kind);
    try {
      const start = await visuals.generateImage(params);
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
      data.onUpdate(id, { ...patch, url: image.url, localPath: image.local_path });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(null);
    }
  }

  function onGenerate() {
    run('generate', {
      prompt,
      stylePrompt: data.mergedStylePrompt,
      styleReferenceImages: [...(data.inputImagePaths ?? []), ...(data.mergedStyleReferenceImages ?? []), ...(data.mergedEntityReferenceImages ?? [])],
    }, { prompt });
  }

  // Sends the current image as the edit model's input (visuals/providers/
  // fal.py switches to FAL_IMAGE_EDIT_MODEL whenever image_paths is set),
  // always first, so it stays the picture being modified. Anything wired
  // into image:in follows it -- an explicit choice, unlike the style/agent/
  // place references, which are left out so the model doesn't blend
  // several pictures instead of changing this one. The style *prompt*
  // still rides along, so an edit keeps the same look.
  function onEdit() {
    if (!data.localPath) return;
    run('edit', { prompt: editPrompt, imagePaths: [data.localPath, ...(data.inputImagePaths ?? [])], stylePrompt: data.mergedStylePrompt }, { editPrompt });
  }

  return (
    <NodeShell
      typeLabel={`Frame ${String(data.shotIndex + 1).padStart(2, '0')}`}
      selected={selected}
      running={pending !== null}
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
      {data.hasImageRef && (
        <div className="node-subtitle">
          {data.inputImagePaths?.length
            ? `+ ${data.inputImagePaths.length} input image${data.inputImagePaths.length === 1 ? '' : 's'}`
            : 'input image not generated yet'}
        </div>
      )}
      <div className="node-controls">
        <button className="node-run-btn" disabled={pending !== null || !prompt.trim()} onClick={onGenerate}>
          {pending === 'generate' ? 'generating…' : data.url ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>
      {data.url && (
        <>
          <textarea
            className="node-prompt-input"
            rows={2}
            value={editPrompt}
            placeholder="Edit this image, e.g. make it night, add rain on the glass…"
            onChange={(e) => setEditPrompt(e.target.value)}
            onBlur={() => editPrompt !== (data.editPrompt ?? '') && data.onUpdate(id, { editPrompt })}
          />
          <div className="node-controls">
            <button
              className="node-run-btn"
              disabled={pending !== null || !editPrompt.trim() || !data.localPath || !canEdit}
              title={canEdit ? 'Apply the edit to the current image' : 'The active image provider cannot edit images'}
              onClick={onEdit}
            >
              {pending === 'edit' ? 'editing…' : '✎ edit image'}
            </button>
          </div>
        </>
      )}
      {error && <div className="node-error-text">{error}</div>}

      <Port id="image:in" type="image" direction="in" label="image" optional={!data.hasImageRef} top="calc(100% - 94px)" />
      <Port id="agent:in" type="agent" direction="in" label="agent" optional={!data.hasAgentRef} top="calc(100% - 74px)" />
      <Port id="place:in" type="place" direction="in" label="place" optional={!data.hasPlaceRef} top="calc(100% - 54px)" />
      <Port id="shot:in" type="shot" direction="in" label="shot" optional top="calc(100% - 34px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional={!data.hasStyleRef} top="calc(100% - 14px)" />
      <Port id="image:out" type="image" direction="out" label="image" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
