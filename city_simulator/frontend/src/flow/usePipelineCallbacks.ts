// The Simulation/Treatment/Frame/Video/Style node callbacks -- identical
// logic regardless of which canvas hosts them (they only ever mutate
// this canvas's own nodes/edges state), so every canvas wanting the full
// node palette shares this one implementation rather than re-deriving it.
import { useCallback } from 'react';
import type { Node, Edge } from '@xyflow/react';
import { graph, stylesApi } from '../api/client';
import type { GraphEdge, GraphNode, Style } from '../api/types';
import { newNodeId } from './graphIds';
import { nonOverlappingGridPositions, type Rect } from './layout';
import type { FrameNodeData } from './nodes/FrameNode';
import type { StyleNodeData } from './nodes/StyleNode';
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

// Frame/Video generations no longer attach to any entity (self-contained,
// like ScratchImage -- see FrameNode.tsx/VideoNode.tsx), so this hook no
// longer needs an onDataRefresh callback: nothing it produces changes
// HistoryData/cityData anymore. Image/Style still do their own
// onDataRefresh calls where they're wired (useAddNodeActions.ts /
// EntityCanvas.tsx's onImageUpdate), unrelated to this hook.
export function usePipelineCallbacks(
  setNodes: (fn: (prev: Node[] | null) => Node[] | null) => void,
  setEdges: (fn: (prev: Edge[]) => Edge[]) => void,
  // Navigates to the Storyboard's own drill-in route -- unlike every
  // other callback here, this one leaves the canvas, so it has to come
  // from the caller (each canvas already owns its own onExpandAgent/
  // onExpandPlace the same way, see entityNodeKit.ts's callers).
  onExpandStoryboard: (storyboardId: string) => void,
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

  // Frame/Video no longer attach their generated media to any entity (see
  // FrameNode.tsx/VideoNode.tsx -- self-contained now, like ScratchImage),
  // so their own generations have nothing left to refresh onDataRefresh
  // for; only Image (still entity-attached, per-agent/per-place) and
  // Style still trigger it, elsewhere.
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

  // Creates one Storyboard node and seeds its own drill-in canvas
  // directly via a PUT to `storyboard:<id>` -- confirmed safe for a
  // brand-new scope (citystate/graph_store.py's _empty() already defaults
  // to version:1/rev:0, exactly what a first save needs, no prior GET
  // required). The seed is Agent/Location/Style reference GraphNodes for
  // whatever's connected to the Treatment's own agent:in/place:in/
  // style:in ports, plus one Frame GraphNode per shot, with edges wiring
  // every reference to every Frame's own agent:in/place:in/style:in --
  // mirrors what the user would have dragged in by hand, so Frame's
  // existing reference-image/style feed just works the instant the
  // Storyboard is opened.
  const onCreateStoryboard = useCallback(
    (
      treatmentNodeId: string,
      shots: string[],
      agentIds: string[],
      placeIds: string[],
      styleIds: string[],
      agentNames: string[],
      placeNames: string[],
      styleNames: string[],
    ) => {
      const storyboardId = newNodeId('storyboard');

      const agentRefNodes: GraphNode[] = agentIds.map((characterId, i) => ({
        id: `agent:${characterId}`,
        type: 'agent',
        position: { x: i * 280, y: 0 },
        data: { characterId },
      }));
      const placeRefNodes: GraphNode[] = placeIds.map((placeId, i) => ({
        id: `place:${placeId}`,
        type: 'location',
        position: { x: i * 280, y: 220 },
        data: { placeId },
      }));
      // Style is a library reference, not a citystate entity (see
      // StyleNode.tsx) -- the seeded node still just needs `{styleId}`,
      // same shape a manually-dropped Style node uses.
      const styleRefNodes: GraphNode[] = styleIds.map((styleId, i) => ({
        id: `style:${styleId}`,
        type: 'style',
        position: { x: i * 280, y: 440 },
        data: { styleId },
      }));
      // A single horizontal row, not a wrapping grid -- storyboard shots
      // read left-to-right in sequence, so wrapping them into rows (the
      // original 3-column layout) broke that reading order and, since
      // this layout assumes a uniform cell size while a never-resized
      // node actually shrink-to-fits its own content (see the width/
      // height fallback below), let same-row neighbors overlap. Width is
      // baked in explicitly for the same reason: 540 matches FrameNode's
      // own NodeResizer floor, so every shot renders at the identical
      // size from the moment it's created, and FRAME_GUTTER (60px) is
      // guaranteed clear space between them regardless.
      const FRAME_WIDTH = 540;
      const FRAME_HEIGHT = 430;
      const FRAME_GUTTER = 60;
      const frameNodes: GraphNode[] = shots.map((shotText, i) => ({
        id: newNodeId('frame'),
        type: 'frame',
        position: { x: i * (FRAME_WIDTH + FRAME_GUTTER), y: 660 },
        width: FRAME_WIDTH,
        height: FRAME_HEIGHT,
        data: { shotIndex: i, prompt: shotText },
      }));

      const seedEdges: GraphEdge[] = [];
      for (const frame of frameNodes) {
        for (const ref of agentRefNodes) {
          seedEdges.push({ id: `e:${ref.id}->${frame.id}:agent`, source: ref.id, sourceHandle: 'agent:out', target: frame.id, targetHandle: 'agent:in' });
        }
        for (const ref of placeRefNodes) {
          seedEdges.push({ id: `e:${ref.id}->${frame.id}:place`, source: ref.id, sourceHandle: 'place:out', target: frame.id, targetHandle: 'place:in' });
        }
        for (const ref of styleRefNodes) {
          seedEdges.push({ id: `e:${ref.id}->${frame.id}:style`, source: ref.id, sourceHandle: 'style:out', target: frame.id, targetHandle: 'style:in' });
        }
      }

      graph
        .put(storyboardId, {
          version: 1,
          rev: 0,
          viewport: { x: 0, y: 0, zoom: 1 },
          nodes: [...agentRefNodes, ...placeRefNodes, ...styleRefNodes, ...frameNodes],
          edges: seedEdges,
        })
        .catch((e) => console.error('failed to seed storyboard', e));

      setNodes((prev) => {
        const list = prev ?? [];
        const treatmentNode = list.find((n) => n.id === treatmentNodeId);
        const obstacles: Rect[] = list.map((n) => ({ x: n.position.x, y: n.position.y, ...nodeFootprint(n) }));
        const [position] = nonOverlappingGridPositions(
          1,
          {
            itemWidth: 300,
            itemHeight: 220,
            columns: 1,
            gutter: 60,
            originX: (treatmentNode?.position.x ?? 0) + 380,
            originY: treatmentNode?.position.y ?? 0,
          },
          obstacles,
        );

        const storyboardNode: Node = {
          id: storyboardId,
          type: 'storyboard',
          position,
          data: { shotCount: shots.length, contextAgentNames: agentNames, contextPlaceNames: placeNames, contextStyleNames: styleNames, onExpand: onExpandStoryboard },
        };
        return [...list, storyboardNode];
      });

      setEdges((prevEdges) => [
        ...prevEdges,
        { id: `e:${treatmentNodeId}->${storyboardId}`, source: treatmentNodeId, sourceHandle: 'shots:out', target: storyboardId, targetHandle: 'shots:in' },
      ]);
    },
    [setNodes, setEdges, onExpandStoryboard],
  );

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
    onCreateStoryboard,
    onExpandStoryboard,
    onFrameUpdate,
    onVideoUpdate,
    onStyleLoaded,
    onStyleUpdate,
    onStyleDelete,
  };
}
