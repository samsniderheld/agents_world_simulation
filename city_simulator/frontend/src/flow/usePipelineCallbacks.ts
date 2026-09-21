// The Simulation/Treatment/Frame/Video/Style node callbacks -- identical
// logic regardless of which canvas hosts them (they only ever mutate
// this canvas's own nodes/edges state), so every canvas wanting the full
// node palette shares this one implementation rather than re-deriving it.
import { useCallback } from 'react';
import type { Node, Edge } from '@xyflow/react';
import { stylesApi } from '../api/client';
import type { Style } from '../api/types';
import { newNodeId } from './graphIds';
import { nonOverlappingGridPositions, type Rect } from './layout';
import type { FrameNodeData } from './nodes/FrameNode';
import type { StyleNodeData } from './nodes/StyleNode';
import type { TreatmentNodeData } from './nodes/TreatmentNode';
import type { VideoNodeData } from './nodes/VideoNode';
import type { PipelineCallbacks } from './pipeline';

// Real rendered size once React Flow has measured a node (n.measured),
// falling back to a type-appropriate guess for one that hasn't rendered
// yet -- good enough for "don't land a new Frame on top of you," not
// meant to be pixel-exact. Media nodes' floor comes straight from
// FrameNode/ImageNode/VideoNode's own NodeShell minWidth/minHeight.
const MEDIA_NODE_TYPES = new Set(['frame', 'image', 'video', 'scratch-image']);
const WIDE_NODE_TYPES = new Set(['sim', 'treatment', 'style']);

function nodeFootprint(n: Node): { width: number; height: number } {
  if (n.measured?.width && n.measured?.height) return { width: n.measured.width, height: n.measured.height };
  if (n.width && n.height) return { width: n.width, height: n.height };
  if (MEDIA_NODE_TYPES.has(n.type ?? '')) return { width: 540, height: 430 };
  if (WIDE_NODE_TYPES.has(n.type ?? '')) return { width: 300, height: 220 };
  return { width: 240, height: 160 };
}

export function usePipelineCallbacks(
  setNodes: (fn: (prev: Node[] | null) => Node[] | null) => void,
  setEdges: (fn: (prev: Edge[]) => Edge[]) => void,
  // Called whenever a Frame/Video generation actually attaches new media
  // (patch.mediaId set), not on every prompt edit -- without this, the
  // canvas's own HistoryData/cityData snapshot (which agent:in/place:in
  // reference-image lookups read from) never learns the new media exists
  // until the whole screen is reloaded, so a node generated right after
  // wiring up a reference silently sends an empty reference list.
  onDataRefresh?: () => void,
): PipelineCallbacks {
  const onTicksChange = useCallback((nodeId: string, ticks: number) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ticks } } : n)) : prev));
  }, [setNodes]);

  const onDirectiveChange = useCallback((nodeId: string, directive: string) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, directive } } : n)) : prev));
  }, [setNodes]);

  const onProviderChange = useCallback((nodeId: string, provider: string) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, provider } } : n)) : prev));
  }, [setNodes]);

  const onChatModelChange = useCallback((nodeId: string, chatModel: string) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, chatModel } } : n)) : prev));
  }, [setNodes]);

  const onVerboseChange = useCallback((nodeId: string, verbose: boolean) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, verbose } } : n)) : prev));
  }, [setNodes]);

  const onSubjectChange = useCallback((nodeId: string, subjectId: string) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, subjectId } } : n)) : prev));
  }, [setNodes]);

  const onTreatmentGenerated = useCallback((nodeId: string, text: string, shots: string[]) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, text, shots } } : n)) : prev));
  }, [setNodes]);

  const onTreatmentProviderChange = useCallback((nodeId: string, provider: string) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, provider } } : n)) : prev));
  }, [setNodes]);

  const onTreatmentModelChange = useCallback((nodeId: string, model: string) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, model } } : n)) : prev));
  }, [setNodes]);

  const onFrameUpdate = useCallback(
    (nodeId: string, patch: Partial<FrameNodeData>) => {
      setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
      if (patch.mediaId) onDataRefresh?.();
    },
    [setNodes, onDataRefresh],
  );

  const onVideoUpdate = useCallback(
    (nodeId: string, patch: Partial<VideoNodeData>) => {
      setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
      if (patch.mediaId) onDataRefresh?.();
    },
    [setNodes, onDataRefresh],
  );

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

  // Deletes the library entry this node points at (not just the node
  // itself) -- a placed Style node is the one place on canvas that
  // clearly "owns" one specific style, so removing it here is the same
  // destructive action as the Styles drawer's own delete button, just
  // reached from the node instead of the list.
  const onStyleDelete = useCallback(
    (nodeId: string) => {
      setNodes((prev) => {
        if (!prev) return prev;
        const node = prev.find((n) => n.id === nodeId);
        const styleId = node ? (node.data as StyleNodeData).styleId : undefined;
        if (styleId) stylesApi.remove(styleId).catch((e) => console.error('failed to delete style', e));
        return prev.filter((n) => n.id !== nodeId);
      });
      setEdges((prev) => prev.filter((e) => e.source !== nodeId && e.target !== nodeId));
    },
    [setNodes, setEdges],
  );

  // Emit frames: the subject is read from the treatment node's own
  // current state (not re-derived from candidates) since by the time you
  // click this, a subject has already been chosen -- one Frame per shot,
  // fanned out to the right of the Treatment node in a grid, each
  // pre-wired with a shots:out -> shot:in edge so the pipeline reads as
  // connected the instant it appears, not as orphaned nodes you'd have to
  // wire by hand. Item size is Frame's own resize floor (540x430, see
  // FrameNode.tsx's NodeShell minWidth/minHeight) with a 60px gutter, and
  // every EXISTING node on the canvas (not just the other new frames) is
  // treated as an obstacle, so a batch dropped into an already-busy
  // canvas lands in genuinely free space instead of stacking on top of
  // whatever happened to already be there.
  const onEmitFrames = useCallback((treatmentNodeId: string, shots: string[]) => {
    setNodes((prev) => {
      if (!prev) return prev;
      const treatmentNode = prev.find((n) => n.id === treatmentNodeId);
      const subjectId = treatmentNode && (treatmentNode.data as TreatmentNodeData).subjectId;
      if (!treatmentNode || !subjectId) return prev;

      const obstacles: Rect[] = prev.map((n) => ({ x: n.position.x, y: n.position.y, ...nodeFootprint(n) }));
      const positions = nonOverlappingGridPositions(
        shots.length,
        { itemWidth: 540, itemHeight: 430, columns: 3, gutter: 60, originX: treatmentNode.position.x + 380, originY: treatmentNode.position.y },
        obstacles,
      );

      const newNodes: Node[] = shots.map((shotText, i) => ({
        id: newNodeId('frame'),
        type: 'frame',
        position: positions[i],
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

  return {
    onTicksChange,
    onDirectiveChange,
    onProviderChange,
    onChatModelChange,
    onVerboseChange,
    onSubjectChange,
    onTreatmentGenerated,
    onTreatmentProviderChange,
    onTreatmentModelChange,
    onEmitFrames,
    onFrameUpdate,
    onVideoUpdate,
    onStyleLoaded,
    onStyleUpdate,
    onStyleDelete,
  };
}
