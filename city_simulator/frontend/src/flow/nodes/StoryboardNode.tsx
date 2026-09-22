import { useEffect, useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { graph, visuals } from '../../api/client';
import { useLightboxStore } from '../../state/lightboxStore';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface StoryboardNodeData extends Record<string, unknown> {
  // A snapshot taken once at creation (see usePipelineCallbacks.ts's
  // onCreateStoryboard) -- not kept live in sync with the inner canvas
  // afterward, the same honesty tradeoff Frame's own entityId snapshot
  // already makes. Adding/removing Frames inside won't update this count.
  shotCount: number;
  contextAgentNames: string[];
  contextPlaceNames: string[];
  contextStyleNames: string[];
  // Whether agent:in/place:in/style:in each actually have an edge -- lets
  // a manually-created empty Storyboard (no shots yet) still show its own
  // context connections as live, same pattern as Frame's own ports.
  hasAgentRef?: boolean;
  hasPlaceRef?: boolean;
  hasStyleRef?: boolean;
  onExpand: (storyboardId: string) => void;
}

export type StoryboardNodeType = Node<StoryboardNodeData, 'storyboard'>;

interface FrameThumb {
  id: string;
  shotIndex: number;
  url: string;
}

// A container node -- its real content (Frame nodes, one per shot, plus
// whatever Agent/Location/Style context got carried through from the
// Treatment that created it) lives in its own drilled-in canvas, a real
// route/scope exactly like an Agent or Place's own canvas (not a React
// Flow parent/child subflow -- see routes/router.ts's own comment on why).
export function StoryboardNode({ id, data, selected }: NodeProps<StoryboardNodeType>) {
  const context = [...data.contextAgentNames, ...data.contextPlaceNames, ...data.contextStyleNames];
  const [thumbs, setThumbs] = useState<FrameThumb[]>([]);
  const openLightbox = useLightboxStore((s) => s.open);

  // The Frame nodes themselves live in this Storyboard's own persisted
  // graph, not this canvas's nodes/edges (this node's own `id` doubles as
  // that graph's scope -- see usePipelineCallbacks.ts's
  // onCreateStoryboard), so previewing their images here means a direct
  // fetch rather than something pipeline.ts's enrichment can derive.
  // Fetched once on mount, same as StyleNode's own style fetch -- this
  // node remounts fresh whenever its canvas reloads (e.g. navigating back
  // after generating frames inside), which is enough to stay current
  // without polling.
  useEffect(() => {
    let cancelled = false;
    graph
      .get(id)
      .then((doc) => {
        if (cancelled) return;
        const frames = doc.nodes
          .filter((n) => n.type === 'frame' && typeof n.data.url === 'string')
          .map((n) => ({ id: n.id, shotIndex: (n.data.shotIndex as number) ?? 0, url: n.data.url as string }))
          .sort((a, b) => a.shotIndex - b.shotIndex);
        setThumbs(frames);
      })
      .catch(() => setThumbs([]));
    return () => {
      cancelled = true;
    };
  }, [id]);

  return (
    <NodeShell typeLabel="Storyboard" selected={selected} onExpand={() => data.onExpand(id)} wide minWidth={340}>
      <div className="node-title">Storyboard</div>
      <div className="node-grounding">
        {data.shotCount > 0 ? `${data.shotCount} shot${data.shotCount === 1 ? '' : 's'}` : 'empty -- add Frame nodes inside'}
      </div>
      {context.length > 0 && <div className="node-subtitle">context: {context.join(', ')}</div>}

      {thumbs.length > 0 && (
        <div className="style-ref-grid">
          {thumbs.map((t) => (
            <div className="style-ref-item" key={t.id}>
              <img
                src={visuals.fileUrl(t.url)}
                alt=""
                onClick={(e) => {
                  e.stopPropagation();
                  openLightbox(visuals.fileUrl(t.url));
                }}
              />
            </div>
          ))}
        </div>
      )}

      <Port id="agent:in" type="agent" direction="in" label="agent" optional={!data.hasAgentRef} top="calc(100% - 74px)" />
      <Port id="place:in" type="place" direction="in" label="place" optional={!data.hasPlaceRef} top="calc(100% - 54px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional={!data.hasStyleRef} top="calc(100% - 34px)" />
      <Port id="shots:in" type="shot" direction="in" label="shots" optional top="calc(100% - 14px)" />
    </NodeShell>
  );
}
