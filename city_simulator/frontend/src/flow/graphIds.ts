// Shared between every canvas (CityCanvas, ScratchScreen): converting
// React Flow's Edge shape to/from the persisted GraphEdge shape, and
// minting new node ids for nodes created on-canvas (not derived from an
// entity id).
import type { Edge } from '@xyflow/react';
import type { GraphEdge } from '../api/types';

export function toGraphEdge(e: Edge): GraphEdge {
  return { id: e.id, source: e.source, sourceHandle: e.sourceHandle ?? '', target: e.target, targetHandle: e.targetHandle ?? '' };
}

export function toFlowEdge(e: GraphEdge): Edge {
  return { id: e.id, source: e.source, sourceHandle: e.sourceHandle, target: e.target, targetHandle: e.targetHandle, type: 'default' };
}

let nextNodeSeq = 1;
export function newNodeId(prefix: string): string {
  return `${prefix}:${Date.now()}_${nextNodeSeq++}`;
}
