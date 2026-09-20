import { useCallback, useEffect, useRef, useState } from 'react';
import type { Connection, Edge, Node, NodeMouseHandler } from '@xyflow/react';
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  BackgroundVariant,
  Controls,
  Panel,
  ReactFlow,
  ReactFlowProvider,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { city, history, stylesApi } from '../api/client';
import type { Character, GraphNode, HistoryData, MediaItem, Place, Style } from '../api/types';
import { Inspector } from '../inspector/Inspector';
import { navigate } from '../routes/router';
import { useJobStore } from '../state/jobStore';
import './canvas.css';
import { isValidConnection as checkValidConnection } from './edgeRules';
import { gridPosition } from './layout';
import { AgentNode } from './nodes/AgentNode';
import { FrameNode, type FrameNodeData } from './nodes/FrameNode';
import { LocationNode } from './nodes/LocationNode';
import { MissingNode } from './nodes/MissingNode';
import { SimulationNode } from './nodes/SimulationNode';
import { StyleNode } from './nodes/StyleNode';
import { TreatmentNode, type TreatmentNodeData } from './nodes/TreatmentNode';
import { VideoNode, type VideoNodeData } from './nodes/VideoNode';
import { NotOnCanvasTray } from './NotOnCanvasTray';
import { enrichPipelineNodes, pipelineToGraphNode, toPipelineRenderNode } from './pipeline';
import { newNodeId, toFlowEdge, toGraphEdge } from './graphIds';
import { reconcile } from './reconcile';
import { usePersistedGraph } from './usePersistedGraph';
import type { Selection } from './selection';

const nodeTypes = {
  agent: AgentNode,
  location: LocationNode,
  missing: MissingNode,
  sim: SimulationNode,
  treatment: TreatmentNode,
  frame: FrameNode,
  video: VideoNode,
  style: StyleNode,
};

const PIPELINE_TYPES = new Set(['sim', 'treatment', 'frame', 'video', 'style']);

function firstImageUrl(items: MediaItem[] | undefined): string | undefined {
  const hit = items?.find((m) => m.kind === 'image');
  return hit ? city.fileUrl(hit.url) : undefined;
}

// The one place that knows how to go both directions between a node's
// persisted shape (an entity reference only -- see graph_store.py's
// docstring) and its enriched render shape. Agent/Location/Missing here;
// the pipeline node types (sim/treatment/frame/video) have their own
// pair in pipeline.ts, since their persisted shape is "own fields only,"
// not an entity reference.
function toRenderNode(
  gn: GraphNode,
  data: HistoryData,
  onExpandAgent: (id: string) => void,
  onExpandPlace: (id: string) => void,
  onRemoveMissing: (nodeId: string) => void,
): Node | null {
  if (gn.type === 'agent') {
    const characterId = gn.data.characterId as string;
    const character = data.characters.find((c) => c.id === characterId);
    if (!character) return null;
    return {
      id: gn.id,
      type: 'agent',
      position: gn.position,
      data: { character, thumbUrl: firstImageUrl(data.media[characterId]), onExpand: onExpandAgent },
    };
  }
  if (gn.type === 'location') {
    const placeId = gn.data.placeId as string;
    const place = data.places.find((p) => p.id === placeId);
    if (!place) return null;
    const residentCount = data.characters.filter((c) => c.place_id === placeId).length;
    return {
      id: gn.id,
      type: 'location',
      position: gn.position,
      data: { place, thumbUrl: firstImageUrl(data.media[placeId]), residentCount, onExpand: onExpandPlace },
    };
  }
  if (gn.type === 'missing') {
    return { id: gn.id, type: 'missing', position: gn.position, data: { entityId: gn.data.entityId as string, onRemove: onRemoveMissing } };
  }
  return null;
}

function toGraphNode(n: Node): GraphNode {
  if (n.type === 'agent') {
    const character = (n.data as { character: Character }).character;
    return { id: n.id, type: 'agent', position: n.position, data: { characterId: character.id } };
  }
  if (n.type === 'location') {
    const place = (n.data as { place: Place }).place;
    return { id: n.id, type: 'location', position: n.position, data: { placeId: place.id } };
  }
  if (n.type === 'missing') {
    return { id: n.id, type: 'missing', position: n.position, data: { entityId: (n.data as { entityId: string }).entityId } };
  }
  const pipelineNode = pipelineToGraphNode(n);
  if (pipelineNode) return pipelineNode;
  throw new Error(`unknown node type: ${n.type}`);
}

function CanvasInner({ cityId, data }: { cityId: string; data: HistoryData }) {
  const { doc, save } = usePersistedGraph(`city:${cityId}`);
  const [selection, setSelection] = useState<Selection>({ kind: 'city' });
  const [nodes, setNodes] = useState<Node[] | null>(null);
  const [edges, setEdges] = useState<Edge[]>([]);
  const initializedFor = useRef<string | null>(null);

  const onExpandAgent = useCallback((id: string) => navigate({ kind: 'agent', cityId, agentId: id }), [cityId]);
  const onExpandPlace = useCallback((id: string) => navigate({ kind: 'place', cityId, placeId: id }), [cityId]);
  const onRemoveMissing = useCallback((nodeId: string) => {
    setNodes((prev) => (prev ? prev.filter((n) => n.id !== nodeId) : prev));
    setEdges((prev) => prev.filter((e) => e.source !== nodeId && e.target !== nodeId));
  }, []);

  const onTicksChange = useCallback((nodeId: string, ticks: number) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ticks } } : n)) : prev));
  }, []);
  const onSubjectChange = useCallback((nodeId: string, subjectId: string) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, subjectId } } : n)) : prev));
  }, []);
  const onTreatmentGenerated = useCallback((nodeId: string, text: string, shots: string[]) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, text, shots } } : n)) : prev));
  }, []);
  const onFrameUpdate = useCallback((nodeId: string, patch: Partial<FrameNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);
  const onVideoUpdate = useCallback((nodeId: string, patch: Partial<VideoNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);
  const onStyleLoaded = useCallback((nodeId: string, style: Style) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, style } } : n)) : prev));
  }, []);
  const onStyleUpdate = useCallback((nodeId: string, patch: Partial<Style>) => {
    setNodes((prev) =>
      prev
        ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, style: { ...(n.data as { style: Style }).style, ...patch } } } : n))
        : prev,
    );
  }, []);

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
  }, [onFrameUpdate]);

  const pipelineCallbacks = {
    onTicksChange,
    onSubjectChange,
    onTreatmentGenerated,
    onEmitFrames,
    onFrameUpdate,
    onVideoUpdate,
    onStyleLoaded,
    onStyleUpdate,
  };

  // Seeded exactly once per (doc, data) pairing -- see the equivalent
  // comment this replaced in Phase 2 for why `data.generated_at` is part
  // of the key, not just `doc.rev`.
  useEffect(() => {
    if (!doc) return;
    const key = `${doc.rev}:${data.generated_at}`;
    if (initializedFor.current === key && nodes) return;
    initializedFor.current = key;

    const agentIds = data.characters.map((c) => c.id);
    const placeIds = data.places.map((p) => p.id);
    const agentRecon = reconcile(doc.nodes.filter((n) => n.type === 'agent'), agentIds, (n) => n.data.characterId as string);
    const placeRecon = reconcile(doc.nodes.filter((n) => n.type === 'location'), placeIds, (n) => n.data.placeId as string);
    const alreadyMissing = doc.nodes.filter((n) => n.type === 'missing');
    const pipelineGraphNodes = doc.nodes.filter((n) => PIPELINE_TYPES.has(n.type));

    const persisted = [...agentRecon.present, ...placeRecon.present, ...alreadyMissing];
    const danglingAsMissing: GraphNode[] = [...agentRecon.missing, ...placeRecon.missing].map((n) => ({
      id: n.id,
      type: 'missing',
      position: n.position,
      data: { entityId: (n.data.characterId ?? n.data.placeId) as string },
    }));

    const built = [...persisted, ...danglingAsMissing]
      .map((gn) => toRenderNode(gn, data, onExpandAgent, onExpandPlace, onRemoveMissing))
      .filter((n): n is Node => n !== null);
    const builtPipeline = pipelineGraphNodes.map((gn) => toPipelineRenderNode(gn, data, pipelineCallbacks)).filter((n): n is Node => n !== null);

    // Edges referencing a node that didn't make it through (e.g. an
    // agent id that no longer exists and became `missing` under a
    // different id scheme) are dropped -- see the general edge-pruning
    // effect below for the steady-state version of this same rule.
    const nodeIds = new Set([...built, ...builtPipeline].map((n) => n.id));
    const builtEdges = doc.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target)).map(toFlowEdge);

    setNodes([...built, ...builtPipeline]);
    setEdges(builtEdges);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, data]);

  // Prune edges whenever a node disappears through any path (missing's
  // Remove button, or the user pressing delete on a selected node).
  useEffect(() => {
    if (!nodes) return;
    const ids = new Set(nodes.map((n) => n.id));
    setEdges((prev) => prev.filter((e) => ids.has(e.source) && ids.has(e.target)));
  }, [nodes]);

  // Autosave whenever the working graph changes.
  useEffect(() => {
    if (nodes) save(nodes.map(toGraphNode), edges.map(toGraphEdge));
  }, [nodes, edges, save]);

  const onNodesChange = useCallback((changes: Parameters<typeof applyNodeChanges>[0]) => {
    setNodes((nds) => (nds ? applyNodeChanges(changes, nds) : nds));
  }, []);
  const onEdgesChange = useCallback((changes: Parameters<typeof applyEdgeChanges>[0]) => {
    setEdges((eds) => applyEdgeChanges(changes, eds));
  }, []);

  const isValidConnection = useCallback((c: Edge | Connection) => checkValidConnection(c.sourceHandle, c.targetHandle), []);
  const onConnect = useCallback((c: Connection) => {
    if (!checkValidConnection(c.sourceHandle, c.targetHandle)) return;
    setEdges((eds) => addEdge(c, eds));
  }, []);

  const onNodeClick: NodeMouseHandler = useCallback((_, node) => {
    if (node.type === 'agent') setSelection({ kind: 'agent', characterId: (node.data as { character: Character }).character.id });
    else if (node.type === 'location') setSelection({ kind: 'place', placeId: (node.data as { place: Place }).place.id });
  }, []);

  const onNodeDoubleClick: NodeMouseHandler = useCallback(
    (_, node) => {
      if (node.type === 'agent') onExpandAgent((node.data as { character: Character }).character.id);
      else if (node.type === 'location') onExpandPlace((node.data as { place: Place }).place.id);
    },
    [onExpandAgent, onExpandPlace],
  );

  const notOnCanvas = (() => {
    if (!nodes) return [];
    const onCanvasAgentIds = new Set(nodes.filter((n) => n.type === 'agent').map((n) => (n.data as { character: Character }).character.id));
    const onCanvasPlaceIds = new Set(nodes.filter((n) => n.type === 'location').map((n) => (n.data as { place: Place }).place.id));
    const agents = data.characters.filter((c) => !onCanvasAgentIds.has(c.id)).map((c) => ({ id: c.id, label: c.name, kind: 'agent' as const }));
    const places = data.places.filter((p) => !onCanvasPlaceIds.has(p.id)).map((p) => ({ id: p.id, label: p.name, kind: 'location' as const }));
    return [...agents, ...places];
  })();

  const addToCanvas = useCallback(
    (entry: { id: string; kind: 'agent' | 'location' }) => {
      setNodes((prev) => {
        const list = prev ?? [];
        const position = gridPosition(list.length, { columns: 4, cellWidth: 270, cellHeight: 190 });
        const built =
          entry.kind === 'agent'
            ? toRenderNode({ id: `agent:${entry.id}`, type: 'agent', position, data: { characterId: entry.id } }, data, onExpandAgent, onExpandPlace, onRemoveMissing)
            : toRenderNode({ id: `place:${entry.id}`, type: 'location', position, data: { placeId: entry.id } }, data, onExpandAgent, onExpandPlace, onRemoveMissing);
        return built ? [...list, built] : list;
      });
    },
    [data, onExpandAgent, onExpandPlace, onRemoveMissing],
  );

  const addPipelineNode = useCallback(
    (type: 'sim' | 'treatment' | 'video') => {
      setNodes((prev) => {
        const list = prev ?? [];
        const position = gridPosition(list.filter((n) => PIPELINE_TYPES.has(n.type ?? '')).length, {
          columns: 3,
          cellWidth: 340,
          cellHeight: 260,
          originY: 900,
        });
        const id = newNodeId(type);
        const base = { id, position };
        if (type === 'sim') return [...list, { ...base, type, data: { ticks: 8, agentNames: [], onTicksChange } }];
        if (type === 'treatment')
          return [...list, { ...base, type, data: { candidates: [], onSubjectChange, onGenerated: onTreatmentGenerated, onEmitFrames } }];
        return [...list, { ...base, type, data: { prompt: '', onUpdate: onVideoUpdate } }];
      });
    },
    [onTicksChange, onSubjectChange, onTreatmentGenerated, onEmitFrames, onVideoUpdate],
  );

  // Styles live in the global library (visuals/styles.py), not the graph
  // document -- "+ Style" always mints a fresh library entry rather than
  // opening a picker over existing ones, a deliberate v1 scope cut (see
  // the design spec's own note that a style authored elsewhere should be
  // selectable here -- worth adding once there's more than one style to
  // pick from in practice).
  const addStyleNode = useCallback(async () => {
    let created;
    try {
      created = await stylesApi.create({ name: 'New Style', stylePrompt: '' });
    } catch (e) {
      // No node exists yet to show this on, so surfacing it any more
      // gracefully means a toast system this app doesn't have yet --
      // console.error at least beats an unhandled rejection.
      console.error('failed to create style', e);
      return;
    }
    setNodes((prev) => {
      const list = prev ?? [];
      const position = gridPosition(list.filter((n) => PIPELINE_TYPES.has(n.type ?? '')).length, {
        columns: 3,
        cellWidth: 340,
        cellHeight: 260,
        originY: 900,
      });
      return [
        ...list,
        { id: newNodeId('style'), type: 'style', position, data: { styleId: created.style.id, style: created.style, onLoaded: onStyleLoaded, onUpdate: onStyleUpdate } },
      ];
    });
  }, [onStyleLoaded, onStyleUpdate]);

  if (!nodes) return <div className="canvas-empty">Loading canvas…</div>;

  const renderNodes = enrichPipelineNodes(nodes, edges, data);

  return (
    <div className="city-canvas-layout">
      <div className="canvas-with-tray">
        <ReactFlow
          nodes={renderNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onNodeClick={onNodeClick}
          onNodeDoubleClick={onNodeDoubleClick}
          onPaneClick={() => setSelection({ kind: 'city' })}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} color="var(--canvas-dot)" />
          <Controls showInteractive={false} />
          <Panel position="top-right" className="canvas-toolbar">
            <button className="node-run-btn" onClick={() => addPipelineNode('sim')}>
              + Simulation
            </button>
            <button className="node-run-btn" onClick={() => addPipelineNode('treatment')}>
              + Treatment
            </button>
            <button className="node-run-btn" onClick={() => addPipelineNode('video')}>
              + Video
            </button>
            <button className="node-run-btn" onClick={addStyleNode}>
              + Style
            </button>
          </Panel>
        </ReactFlow>
        <NotOnCanvasTray entries={notOnCanvas} onAdd={addToCanvas} />
      </div>
      <Inspector selection={selection} data={data} />
    </div>
  );
}

function NotFoundState() {
  return (
    <div className="canvas-empty">
      <p>This city no longer exists.</p>
      <button className="node-run-btn" style={{ flex: 'none', padding: '8px 16px' }} onClick={() => navigate({ kind: 'root' })}>
        ← back to Cities
      </button>
    </div>
  );
}

export function CityCanvas({ cityId }: { cityId: string }) {
  const [data, setData] = useState<HistoryData | null | undefined>(undefined);
  const historyStatus = useJobStore((s) => s.historyStatus);

  // Every other endpoint (agents/run, city/media, etc.) operates on
  // "whichever city is active" implicitly -- see citystate/store.py's
  // docstring -- so opening this canvas has to activate cityId server-
  // side first, not just navigate to it client-side. If it's already the
  // active city this is a cheap no-op re-read, not a real switch.
  const load = useCallback(() => {
    history
      .activateCity(cityId)
      .then((res) => setData(res.city))
      .catch(() => setData(null));
  }, [cityId]);

  useEffect(load, [load]);

  const prevPhase = useRef(historyStatus?.phase);
  useEffect(() => {
    if (prevPhase.current === 'running' && historyStatus?.phase === 'done') load();
    prevPhase.current = historyStatus?.phase;
  }, [historyStatus?.phase, load]);

  if (data === undefined) return <div className="canvas-empty">Loading…</div>;
  if (data === null) return <NotFoundState />;

  return (
    <ReactFlowProvider>
      <CanvasInner cityId={cityId} data={data} />
    </ReactFlowProvider>
  );
}
