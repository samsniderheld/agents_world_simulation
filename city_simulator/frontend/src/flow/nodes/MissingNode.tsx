import type { Node, NodeProps } from '@xyflow/react';
import { NodeShell } from './NodeShell';

export interface MissingNodeData extends Record<string, unknown> {
  entityId: string;
  onRemove: (nodeId: string) => void;
}

export type MissingNodeType = Node<MissingNodeData, 'missing'>;

// A node whose referenced entity (char_*/place_*) no longer exists in the
// active city -- most commonly after a regenerate mints fresh ids. Never
// auto-removed (per the design spec): the user decides whether to drop
// the stale arrangement.
export function MissingNode({ id, data }: NodeProps<MissingNodeType>) {
  return (
    <NodeShell typeLabel="Missing" error>
      <div className="node-subtitle">references {data.entityId}, which no longer exists.</div>
      <button className="node-run-btn" onClick={() => data.onRemove(id)}>
        remove
      </button>
    </NodeShell>
  );
}
