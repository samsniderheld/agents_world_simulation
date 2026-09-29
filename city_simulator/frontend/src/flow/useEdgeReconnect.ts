// Drag a cord's end to detach or move it: grab either end of an edge and
// drop it on another compatible port to re-plug it there, or anywhere else
// (empty canvas, an incompatible port) to remove it. Shared by every canvas
// so they all behave the same; spread the result onto <ReactFlow>.
import { useCallback, useRef } from 'react';
import type { Connection, Edge } from '@xyflow/react';
import { reconnectEdge } from '@xyflow/react';
import { isValidConnection } from './edgeRules';

export function useEdgeReconnect(setEdges: (fn: (prev: Edge[]) => Edge[]) => void) {
  // Whether the edge being dragged landed somewhere valid -- set false at
  // drag start, true only by a successful onReconnect.
  const landed = useRef(true);

  const onReconnectStart = useCallback(() => {
    landed.current = false;
  }, []);

  const onReconnect = useCallback(
    (oldEdge: Edge, connection: Connection) => {
      if (!isValidConnection(connection.sourceHandle, connection.targetHandle)) return;
      landed.current = true;
      setEdges((eds) => reconnectEdge(oldEdge, connection, eds));
    },
    [setEdges],
  );

  const onReconnectEnd = useCallback(
    (_: unknown, edge: Edge) => {
      if (!landed.current) setEdges((eds) => eds.filter((e) => e.id !== edge.id));
      landed.current = true;
    },
    [setEdges],
  );

  return { onReconnectStart, onReconnect, onReconnectEnd };
}
