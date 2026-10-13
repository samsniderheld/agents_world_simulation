import { useEffect, useRef, useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { agentsApi, city, visuals } from '../../api/client';
import type { StoryboardVideoPrompt } from '../../api/types';
import { AspectSelect, type AspectRatio } from './AspectSelect';
import { NodeShell } from './NodeShell';
import { Port } from './Port';
import { ComfyServerField } from './ComfyServerField';
import { ProviderSelect } from './ProviderSelect';
import { useVisualsProviders } from './useProviderCapabilities';
import { useVideoGeneration } from './useVideoGeneration';
import { VideoOptions, VideoSizeOptions, type VideoOptionValues } from './VideoOptions';

export interface VideoNodeData extends Record<string, unknown> {
  // Resolved by the parent from the connected Frame node -- both stay
  // undefined until that Frame has generated something to connect.
  sourceImagePath?: string;
  sourceImageUrl?: string;
  // Resolved from a connected Storyboard (storyboard:in): the clip is then
  // made from reference pictures -- the cast's, then each shot's background
  // -- with a prompt built from the storyboard's treatment
  // (agents/storyboard_video.py), on ComfyUI's MiniMax H3 reference workflow.
  storyboardId?: string;
  storyboardTreatment?: string;
  storyboardAgentIds?: string[];
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
  // From a Storyboard: the prompt as last built. While `prompt` still equals
  // it (not edited by hand), generating rebuilds it first, so it follows
  // the latest backgrounds and the duration.
  autoPrompt?: string;
  // Self-contained, like an Image node's own result -- a generated clip
  // belongs to this node/the treatment it's part of, not to any one
  // entity's media history.
  url?: string;
  localPath?: string;
  onUpdate: (nodeId: string, patch: Partial<VideoNodeData>) => void;
}

export type VideoNodeType = Node<VideoNodeData, 'video'>;

// Two ways to make a clip: animate one image (image:in, a generated Frame),
// or -- with a Storyboard wired to storyboard:in -- a reference-to-video clip
// of the whole storyboard.
export function VideoNode({ id, data, selected }: NodeProps<VideoNodeType>) {
  const [prompt, setPrompt] = useState(data.prompt);
  const { pending, error, setError, generate, generateFromReferences } = useVideoGeneration();
  const providers = useVisualsProviders();
  const fromStoryboard = Boolean(data.storyboardId);
  const comfy = fromStoryboard || (data.provider || providers?.defaults.video) === 'comfyui';
  const [refs, setRefs] = useState<StoryboardVideoPrompt | null>(null);
  const [building, setBuilding] = useState(false);
  // (nothing built yet: an image-to-video prompt is replaced on first build)
  const edited = fromStoryboard && data.autoPrompt !== undefined && prompt !== data.autoPrompt;
  // the workflow's own duration, resolution, ... (what a blank option means)
  const workflowDefaults = providers?.video_workflows?.[fromStoryboard ? 'video_reference' : 'video'];

  // The storyboard's prompt and pictures; the prompt goes in the box unless
  // it's been edited by hand (`force`: even then).
  async function build(force: boolean): Promise<StoryboardVideoPrompt | null> {
    if (!data.storyboardId) return null;
    setBuilding(true);
    setError(null);
    try {
      const res = await agentsApi.storyboardVideoPrompt({
        storyboardId: data.storyboardId,
        treatmentText: data.storyboardTreatment,
        agentIds: data.storyboardAgentIds,
        duration: data.options?.duration,
        style: data.mergedStylePrompt,
      });
      setRefs(res);
      if (force || !edited) {
        setPrompt(res.prompt);
        data.onUpdate(id, { prompt: res.prompt, autoPrompt: res.prompt });
      }
      return res;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setBuilding(false);
    }
  }

  // Wiring a Storyboard in (or reopening the canvas) fetches its pictures,
  // and a first prompt if there isn't one yet.
  const lastStoryboard = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (!data.storyboardId || lastStoryboard.current === data.storyboardId) return;
    lastStoryboard.current = data.storyboardId;
    void build(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.storyboardId]);

  // A new duration moves the shots' cut times: rebuild the prompt (unless
  // it's been edited by hand) so the times shown are the ones sent.
  const lastDuration = useRef(data.options?.duration);
  useEffect(() => {
    if (lastDuration.current === data.options?.duration) return;
    lastDuration.current = data.options?.duration;
    if (fromStoryboard && !edited) void build(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.options?.duration]);

  async function onGenerate() {
    if (fromStoryboard) {
      const res = await build(false);          // the latest backgrounds (and prompt, unless edited)
      if (!res) return;
      if (!res.image_paths.length) {
        setError('nothing to send yet -- generate the storyboard\'s backgrounds or give the cast pictures');
        return;
      }
      const text = edited ? prompt : res.prompt;
      const result = await generateFromReferences(text, res.image_paths, data.aspectRatio ?? '16:9', { ...(data.options ?? {}) },
        data.comfyuiUrl);
      if (result) data.onUpdate(id, { url: result.url, localPath: result.localPath, lastSeed: result.seed });
      return;
    }
    if (!data.sourceImagePath) return;
    const result = await generate(prompt, data.sourceImagePath, data.mergedStylePrompt, data.aspectRatio ?? '16:9', data.provider,
      comfy ? { ...(data.options ?? {}) } : {}, data.comfyuiUrl);
    if (result) data.onUpdate(id, { prompt, url: result.url, localPath: result.localPath, lastSeed: result.seed });
  }

  const noSource = !fromStoryboard && !data.sourceImagePath;
  const pictures = refs?.pictures ?? [];

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
        ) : fromStoryboard && pictures.length > 0 ? (
          <div className="node-ref-strip">
            {pictures.map((p) => (
              <figure key={p.number} title={`<Picture ${p.number}>: ${p.name}`}>
                <img src={p.source === 'city' ? city.fileUrl(p.url) : visuals.fileUrl(p.url)} alt="" />
                <figcaption>
                  {p.number} · {p.name}
                </figcaption>
              </figure>
            ))}
          </div>
        ) : data.sourceImageUrl ? (
          <img src={data.sourceImageUrl} alt="" />
        ) : (
          <div className="node-media-box-empty">🎞️</div>
        )}
      </div>
      {fromStoryboard ? (
        <div className="node-subtitle">
          from the storyboard: {pictures.filter((p) => p.kind === 'character').length} cast and{' '}
          {pictures.filter((p) => p.kind === 'background').length} background pictures · ComfyUI MiniMax H3 reference
        </div>
      ) : (
        noSource && <div className="node-subtitle">connect a generated Frame's image, or a Storyboard</div>
      )}
      {fromStoryboard && refs?.warnings.map((w) => (
        <div key={w} className="node-subtitle node-warning">
          {w}
        </div>
      ))}
      <textarea
        className="node-prompt-input nodrag nowheel"
        rows={fromStoryboard ? 9 : 2}
        value={prompt}
        placeholder={fromStoryboard ? 'Building the prompt from the storyboard…' : 'Describe the motion…'}
        onChange={(e) => setPrompt(e.target.value)}
        onBlur={() => prompt !== data.prompt && data.onUpdate(id, { prompt })}
      />
      {fromStoryboard && (
        <div className="node-controls">
          <span className="node-subtitle">{edited ? 'edited -- kept as written' : 'built from the treatment; rebuilt on generate'}</span>
          <button className="node-link-btn" disabled={building || pending} onClick={() => void build(true)}>
            {building ? 'building…' : '↻ rebuild prompt'}
          </button>
        </div>
      )}
      {comfy && (
        <ComfyServerField kind="video" value={data.comfyuiUrl ?? ''} info={providers}
          onChange={(url) => data.onUpdate(id, { comfyuiUrl: url || undefined })} />
      )}
      {comfy && (
        <VideoSizeOptions value={data.options ?? {}} defaults={workflowDefaults} aspectRatio={data.aspectRatio ?? '16:9'}
          onChange={(options) => data.onUpdate(id, { options })} />
      )}
      {comfy && (
        <VideoOptions value={data.options ?? {}} defaults={workflowDefaults} lastSeed={data.lastSeed}
          onChange={(options) => data.onUpdate(id, { options })} />
      )}
      {error && <div className="node-error-text">{error}</div>}
      <div className="node-controls">
        <AspectSelect value={data.aspectRatio ?? '16:9'} onChange={(v) => data.onUpdate(id, { aspectRatio: v })} />
        {!fromStoryboard && (
          <ProviderSelect kind="video" value={data.provider ?? ''} info={providers} onChange={(v) => data.onUpdate(id, { provider: v || undefined })} />
        )}
        <button className="node-run-btn" disabled={pending || building || noSource || !prompt.trim()} onClick={onGenerate}>
          {pending ? (fromStoryboard ? 'generating… (~20 min)' : 'generating…') : data.url ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>

      <Port id="storyboard:in" type="video" direction="in" label="storyboard" optional={!fromStoryboard} top="calc(100% - 54px)" />
      <Port id="image:in" type="image" direction="in" label="image" optional={fromStoryboard} top="calc(100% - 34px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional={!data.hasStyleRef} top="calc(100% - 14px)" />
      <Port id="video:out" type="video" direction="out" label="video" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
