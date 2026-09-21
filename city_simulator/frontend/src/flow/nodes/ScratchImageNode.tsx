import { useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { visuals } from '../../api/client';
import { pollVisualsUntilDone } from '../../api/pollVisuals';
import { useLightboxStore } from '../../state/lightboxStore';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface ScratchImageNodeData extends Record<string, unknown> {
  prompt: string;
  url?: string;
  localPath?: string;
  // Resolved from a connected Style node, same as Frame/Video nodes --
  // Style is the one node type genuinely shared between the pipeline and
  // scratch boards (it has no entity of its own either).
  mergedStylePrompt?: string;
  mergedStyleReferenceImages?: string[];
  onUpdate: (nodeId: string, patch: { prompt?: string; url?: string; localPath?: string }) => void;
}

export type ScratchImageNodeType = Node<ScratchImageNodeData, 'scratch-image'>;

// Unlike ImageNode/FrameNode, this has no citystate entity to attach its
// result to (a scratch board has no city) -- the generated file's own
// url/local_path is persisted directly on this node instead, in the
// graph document (via api/graph/<scope>). This is exactly the fix for
// the old Studio tab's session-only gallery: closing the tab no longer
// discards the work, since it's a real node in a real persisted canvas.
export function ScratchImageNode({ id, data, selected }: NodeProps<ScratchImageNodeType>) {
  const [prompt, setPrompt] = useState(data.prompt);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const openLightbox = useLightboxStore((s) => s.open);

  async function generate() {
    setError(null);
    setPending(true);
    try {
      const start = await visuals.generateImage({ prompt, stylePrompt: data.mergedStylePrompt, styleReferenceImages: data.mergedStyleReferenceImages });
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
    <NodeShell typeLabel="Image" selected={selected} running={pending} error={Boolean(error)} minWidth={540} minHeight={430}>
      <div
        className={`node-media-box ${data.url ? 'is-expandable' : ''}`}
        onClick={(e) => {
          if (!data.url) return;
          e.stopPropagation();
          openLightbox(visuals.fileUrl(data.url));
        }}
      >
        {data.url ? <img src={visuals.fileUrl(data.url)} alt="" /> : <div className="node-media-box-empty">🖼</div>}
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
        <button className="node-run-btn" disabled={pending || !prompt.trim()} onClick={generate}>
          {pending ? 'generating…' : data.url ? '↻ regenerate' : '▶ generate'}
        </button>
      </div>

      <Port id="style:in" type="style" direction="in" label="style" optional={!data.mergedStylePrompt} top="calc(100% - 14px)" />
      <Port id="image:out" type="image" direction="out" label="image" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
