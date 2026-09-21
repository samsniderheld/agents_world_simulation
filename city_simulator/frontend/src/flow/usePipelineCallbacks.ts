// The Simulation/Treatment/Frame/Video/Style node callbacks -- identical
// logic regardless of which canvas hosts them (they only ever mutate
// this canvas's own nodes/edges state), so every canvas wanting the full
// node palette shares this one implementation rather than re-deriving it.
import { useCallback } from 'react';
import type { Node, Edge } from '@xyflow/react';
import type { Style } from '../api/types';
import { newNodeId } from './graphIds';
import type { FrameNodeData } from './nodes/FrameNode';
import type { TreatmentNodeData } from './nodes/TreatmentNode';
import type { VideoNodeData } from './nodes/VideoNode';
import type { PipelineCallbacks } from './pipeline';

export function usePipelineCallbacks(setNodes: (fn: (prev: Node[] | null) => Node[] | null) => void, setEdges: (fn: (prev: Edge[]) => Edge[]) => void): PipelineCallbacks {
  const onTicksChange = useCallback((nodeId: string, ticks: number) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ticks } } : n)) : prev));
  }, [setNodes]);

  const onSubjectChange = useCallback((nodeId: string, subjectId: string) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, subjectId } } : n)) : prev));
  }, [setNodes]);

  const onTreatmentGenerated = useCallback((nodeId: string, text: string, shots: string[]) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, text, shots } } : n)) : prev));
  }, [setNodes]);

  const onFrameUpdate = useCallback((nodeId: string, patch: Partial<FrameNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, [setNodes]);

  const onVideoUpdate = useCallback((nodeId: string, patch: Partial<VideoNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, [setNodes]);

  const onStyleLoaded = useCallback((nodeId: string, style: Style) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, style } } : n)) : prev));
  }, [setNodes]);

  const onStyleUpdate = useCallback((nodeId: string, patch: Partial<Style>) => {
    setNodes((prev) =>
      prev
        ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, style: { ...(n.data as { style: Style }).style, ...patch } } } : n))
        : prev,
    );
  }, [setNodes]);

  // Emit frames: the subject is read from the treatment node's own
  // current state (not re-derived from candidates) since by the time you
  // click this, a subject has already been chosen -- one Frame per shot,
  // fanned out to the right of the Treatment node, each pre-wired with a
  // shots:out -> shot:in edge so the pipeline reads as connected the
  // instant it appears, not as orphaned nodes you'd have to wire by hand.
  const onEmitFrames = useCallback((treatmentNodeId: string, shots: string[]) => {
    setNodes((prev) => {
      if (!prev) return prev;
      const treatmentNode = prev.find((n) => n.id === treatmentNodeId);
      const subjectId = treatmentNode && (treatmentNode.data as TreatmentNodeData).subjectId;
      if (!treatmentNode || !subjectId) return prev;

      const newNodes: Node[] = shots.map((shotText, i) => ({
        id: newNodeId('frame'),
        type: 'frame',
        position: { x: treatmentNode.position.x + 340, y: treatmentNode.position.y + i * 260 },
        data: { entityId: subjectId, shotIndex: i, prompt: shotText, onUpdate: onFrameUpdate },
      }));

      setEdges((prevEdges) => [
        ...prevEdges,
        ...newNodes.map((fn) => ({
          id: `e:${treatmentNodeId}->${fn.id}`,
          source: treatmentNodeId,
          sourceHandle: 'shots:out',
          target: fn.id,
          targetHandle: 'shot:in',
        })),
      ]);

      return [...prev, ...newNodes];
    });
  }, [setNodes, setEdges, onFrameUpdate]);

  return { onTicksChange, onSubjectChange, onTreatmentGenerated, onEmitFrames, onFrameUpdate, onVideoUpdate, onStyleLoaded, onStyleUpdate };
}
