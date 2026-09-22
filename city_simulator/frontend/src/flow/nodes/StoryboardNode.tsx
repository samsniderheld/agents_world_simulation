import type { Node, NodeProps } from '@xyflow/react';
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

// A container node -- its real content (Frame nodes, one per shot, plus
// whatever Agent/Location/Style context got carried through from the
// Treatment that created it) lives in its own drilled-in canvas, a real
// route/scope exactly like an Agent or Place's own canvas (not a React
// Flow parent/child subflow -- see routes/router.ts's own comment on why).
export function StoryboardNode({ id, data, selected }: NodeProps<StoryboardNodeType>) {
  const context = [...data.contextAgentNames, ...data.contextPlaceNames, ...data.contextStyleNames];

  return (
    <NodeShell typeLabel="Storyboard" selected={selected} onExpand={() => data.onExpand(id)} wide>
      <div className="node-title">Storyboard</div>
      <div className="node-grounding">
        {data.shotCount > 0 ? `${data.shotCount} shot${data.shotCount === 1 ? '' : 's'}` : 'empty -- add Frame nodes inside'}
      </div>
      {context.length > 0 && <div className="node-subtitle">context: {context.join(', ')}</div>}

      <Port id="agent:in" type="agent" direction="in" label="agent" optional={!data.hasAgentRef} top="calc(100% - 74px)" />
      <Port id="place:in" type="place" direction="in" label="place" optional={!data.hasPlaceRef} top="calc(100% - 54px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional={!data.hasStyleRef} top="calc(100% - 34px)" />
      <Port id="shots:in" type="shot" direction="in" label="shots" optional top="calc(100% - 14px)" />
    </NodeShell>
  );
}
