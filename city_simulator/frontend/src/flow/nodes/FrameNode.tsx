import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { city, visuals } from '../../api/client';
import { pollVisualsUntilDone } from '../../api/pollVisuals';
import { useLightboxStore } from '../../state/lightboxStore';
import { AspectSelect, type AspectRatio } from './AspectSelect';
import { NodeShell } from './NodeShell';
import { Port } from './Port';
import { useProviderCapabilities } from './useProviderCapabilities';

export interface FrameNodeData extends Record<string, unknown> {
  // Set on storyboard shots (Treatment's "create storyboard"): the header
  // reads "Shot 03". Absent on an image added from the drawer: "Image".
  shotIndex?: number;
  prompt: string;
  // The second prompt box: an instruction applied to the *current* image
  // ("make it night, add rain") rather than a fresh generation.
  editPrompt?: string;
  // Sent with both generate and edit (see AspectSelect).
  aspectRatio?: AspectRatio;
  // Where the result lives. Either on this node (url/localPath, a file in
  // visuals/data/outputs) or, when saved to an agent's/place's media,
  // that media record (mediaId, in attachTo's media).
  url?: string;
  localPath?: string;
  mediaId?: string;
  // When set, new results are saved into this agent's/place's media (feeds
  // its thumbnail, media grid, and other images' reference photos).
  attachTo?: string;
  // The canvas's own agent/place, when this node sits on one -- what the
  // "save to ... media" checkbox offers. Not persisted.
  ownerEntityId?: string;
  // Resolved by pipeline.ts's enrichPipelineNodes(): the current image's
  // display URL and file path (either kind of result above), and the name
  // of the entity the checkbox would save to.
  imageUrl?: string;
  imagePath?: string;
  attachName?: string;
  // Resolved from connected Style node(s) -- merged (prompts joined with
  // ", ", reference arrays concatenated) since more than one can feed a port.
  mergedStylePrompt?: string;
  mergedStyleReferenceImages?: string[];
  // Photos of any Agent/Location wired into agent:in/place:in, used as
  // reference images alongside the style's.
  mergedEntityReferenceImages?: string[];
  // Whatever's wired into image:in (another Image) -- sent with both
  // generate and edit, first in line ahead of the style/agent/place refs.
  inputImagePaths?: string[];
  // Whether each input port has an edge -- independent of what it resolved
  // to, so a port still shows "connected" before its source has anything.
  hasAgentRef?: boolean;
  hasPlaceRef?: boolean;
  hasStyleRef?: boolean;
  hasImageRef?: boolean;
  onUpdate: (
    nodeId: string,
    patch: {
      prompt?: string;
      editPrompt?: string;
      aspectRatio?: AspectRatio;
      url?: string;
      localPath?: string;
      mediaId?: string;
      attachTo?: string;
    },
  ) => void;
  // Reloads the canvas's city data -- after saving a result into an
  // entity's media, so it shows (and resolves) right away.
  onCityChanged: () => void;
}

export type FrameNodeType = Node<FrameNodeData, 'frame'>;

// The one image-generation node (it replaced separate Frame, agent/place
// Image, and freeform Image nodes). Generates from a prompt with any wired
// style / agent / place / input images, edits the current image, and keeps
// the result on the node -- or, with "save to ... media" ticked (the
// default on an agent's or place's own canvas), in that entity's media.
// Storyboards seed one per shot, wired to their Agent/Location/Style.
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
  const aspect = data.aspectRatio ?? '16:9';
  // Enrichment resolves these; the fallback covers a canvas rendered
  // before its city data has loaded (a node-kept result needs none).
  const imageUrl = data.imageUrl ?? (data.url ? visuals.fileUrl(data.url) : undefined);
  const imagePath = data.imagePath ?? data.localPath;
  const attachCandidate = data.attachTo ?? data.ownerEntityId;

  async function run(kind: 'generate' | 'edit', params: Parameters<typeof visuals.generateImage>[0], patch: { prompt?: string; editPrompt?: string }) {
    setError(null);
    setPending(kind);
    try {
      const start = await visuals.generateImage({ ...params, options: { aspect_ratio: aspect } });
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
      if (data.attachTo) {
        // Moves the file into that entity's media folder and records it.
        const saved = await city.addMedia({
          entityId: data.attachTo,
          kind: 'image',
          url: image.url,
          localPath: image.local_path,
          prompt: params.prompt,
        });
        const media = saved.media[saved.media.length - 1];
        data.onUpdate(id, { ...patch, mediaId: media.id, url: undefined, localPath: undefined });
        data.onCityChanged();
      } else {
        data.onUpdate(id, { ...patch, url: image.url, localPath: image.local_path, mediaId: undefined });
      }
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

  // Sends the current image as the edit model's input (fal switches to its
  // edit model whenever image_paths is set), always first, so it stays the
  // picture being modified. Anything wired into image:in follows it; the
  // style/agent/place references are left out so the model doesn't blend
  // several pictures instead of changing this one. The style *prompt*
  // still rides along, so an edit keeps the same look.
  function onEdit() {
    if (!imagePath) return;
    run('edit', { prompt: editPrompt, imagePaths: [imagePath, ...(data.inputImagePaths ?? [])], stylePrompt: data.mergedStylePrompt }, { editPrompt });
  }

  const label = data.shotIndex != null ? `Shot ${String(data.shotIndex + 1).padStart(2, '0')}` : 'Image';

  return (
    <NodeShell typeLabel={label} selected={selected} running={pending !== null} error={Boolean(error)} minWidth={540} minHeight={430}>
      <div
        className={`node-media-box ${imageUrl ? 'is-expandable' : ''}`}
        onClick={(e) => {
          if (!imageUrl) return;
          e.stopPropagation();
          openLightbox(imageUrl);
        }}
      >
        {imageUrl ? <img src={imageUrl} alt="" /> : <div className="node-media-box-empty">🖼</div>}
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
      {data.hasImageRef && (
        <div className="node-subtitle">
          {data.inputImagePaths?.length
            ? `+ ${data.inputImagePaths.length} input image${data.inputImagePaths.length === 1 ? '' : 's'}`
            : 'input image not generated yet'}
        </div>
      )}
      {attachCandidate && (
        <label className="node-checkbox-row nodrag">
          <input
            type="checkbox"
            checked={Boolean(data.attachTo)}
            onChange={(e) => data.onUpdate(id, { attachTo: e.target.checked ? attachCandidate : undefined })}
          />
          <span className="node-subtitle">save to {data.attachName ?? 'this entity'}'s media</span>
        </label>
      )}
      <div className="node-controls">
        <AspectSelect value={aspect} onChange={(v) => data.onUpdate(id, { aspectRatio: v })} square />
        <button className="node-run-btn" disabled={pending !== null || !prompt.trim()} onClick={onGenerate}>
          {pending === 'generate' ? 'generating…' : imageUrl ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>
      {imageUrl && (
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
              disabled={pending !== null || !editPrompt.trim() || !imagePath || !canEdit}
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
