import type { Node, NodeProps } from '@xyflow/react';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface TextViewerNodeData extends Record<string, unknown> {
  // Resolved by pipeline.ts's enrichPipelineNodes() from whatever's
  // connected to text:in (today, only a Treatment's treatment:out) -- this
  // node holds no state of its own, it's a pure read-only display of
  // whatever text is currently upstream, the same way Frame/Video derive
  // their inputs from a connected node rather than storing a copy.
  text?: string;
}

export type TextViewerNodeType = Node<TextViewerNodeData, 'text-viewer'>;

// A plain text display -- exists because Treatment's own node only shows
// a 2-line preview (it has controls/ports to fit too), so seeing the full
// generated treatment means reading it somewhere else. Connect Treatment's
// treatment:out here to see the whole thing, resizable like any other node.
export function TextViewerNode({ data, selected }: NodeProps<TextViewerNodeType>) {
  return (
    <NodeShell typeLabel="Text" selected={selected} wide>
      {data.text ? (
        <div className="text-viewer-body">{data.text}</div>
      ) : (
        <div className="node-subtitle">connect a Treatment's text to view it here</div>
      )}
      <Port id="text:in" type="treatment" direction="in" label="text" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
