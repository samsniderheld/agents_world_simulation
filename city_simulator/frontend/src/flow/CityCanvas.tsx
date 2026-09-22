import { useCallback, useEffect, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import type { Connection, Edge, Node, NodeMouseHandler, XYPosition } from '@xyflow/react';
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { history } from '../api/client';
import type { Character, GraphNode, HistoryData, Place } from '../api/types';
import { Inspector } from '../inspector/Inspector';
import { navigate } from '../routes/router';
import { useJobStore } from '../state/jobStore';
import './canvas.css';
import { isValidConnection as checkValidConnection } from './edgeRules';
import { entityToGraphNode, toEntityRenderNode } from './entityNodeKit';
import { NewAgentModal } from './NewAgentModal';
import { AgentNode } from './nodes/AgentNode';
import { FrameNode } from './nodes/FrameNode';
import { LocationNode } from './nodes/LocationNode';
import { MissingNode } from './nodes/MissingNode';
import { ScratchImageNode, type ScratchImageNodeData } from './nodes/ScratchImageNode';
import { ScratchMusicNode, type ScratchMusicNodeData } from './nodes/ScratchMusicNode';
import { SimulationNode } from './nodes/SimulationNode';
import { StoryboardNode } from './nodes/StoryboardNode';
import { StyleNode } from './nodes/StyleNode';
import { TextViewerNode } from './nodes/TextViewerNode';
import { TreatmentNode } from './nodes/TreatmentNode';
import { VideoNode } from './nodes/VideoNode';
import { DRAG_MIME, SideDrawer, type DrawerSection } from './SideDrawer';
import { miniMapNodeColor } from './miniMapColor';
import { enrichPipelineNodes, pipelineToGraphNode, toPipelineRenderNode } from './pipeline';
import { toFlowEdge, toGraphEdge } from './graphIds';
import { reconcile } from './reconcile';
import { scratchToGraphNode, toScratchRenderNode } from './scratchNodeKit';
import { useAddNodeActions } from './useAddNodeActions';
import { usePersistedGraph } from './usePersistedGraph';
import { usePipelineCallbacks } from './usePipelineCallbacks';
import { useStylesLibrary } from './useStylesLibrary';
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
  storyboard: StoryboardNode,
  'text-viewer': TextViewerNode,
  'scratch-image': ScratchImageNode,
  'scratch-music': ScratchMusicNode,
};

// Every non-entity-referencing node type -- these have their own graph
// representation (pipeline.ts / scratchNodeKit), not entityNodeKit's
// agent/location/missing mapping. The full palette is available on every
// canvas now (per the requirement that no node type be scoped to
// "wherever it happened to make the most obvious sense"), so this same
// set applies here, in EntityCanvas, and in ScratchScreen alike.
const PIPELINE_TYPES = new Set(['sim', 'treatment', 'frame', 'video', 'style', 'storyboard', 'text-viewer']);
const SCRATCH_TYPES = new Set(['scratch-image', 'scratch-music']);

function CanvasInner({ cityId, data, onDataRefresh }: { cityId: string; data: HistoryData; onDataRefresh: () => void }) {
  const { doc, save } = usePersistedGraph(`city:${cityId}`);
  const { screenToFlowPosition } = useReactFlow();
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
  const onImageUpdate = useCallback((nodeId: string, patch: Partial<ScratchImageNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);
  const onMusicUpdate = useCallback((nodeId: string, patch: Partial<ScratchMusicNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);

  const onExpandStoryboard = useCallback(
    (storyboardId: string) => navigate({ kind: 'storyboard', storyboardId, from: { kind: 'city', cityId } }),
    [cityId],
  );
  const pipeline = usePipelineCallbacks(setNodes, setEdges, onExpandStoryboard);
  const { styles, refresh: refreshStyles, remove: removeStyle } = useStylesLibrary();
  const [newAgentModal, setNewAgentModal] = useState<{ position?: XYPosition } | null>(null);
  const { addToCanvas, addPipelineNode, addStyleNode, addNewAgent, placeAgentNode, addScratchNode } = useAddNodeActions({
    data,
    setNodes,
    onExpandAgent,
    onExpandPlace,
    onRemoveMissing,
    onDataRefresh,
    onStyleCreated: refreshStyles,
    onOpenNewAgentModal: (position) => setNewAgentModal({ position }),
    pipeline,
    onImageUpdate,
    onMusicUpdate,
  });

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
    const scratchGraphNodes = doc.nodes.filter((n) => SCRATCH_TYPES.has(n.type));

    const persisted = [...agentRecon.present, ...placeRecon.present, ...alreadyMissing];
    const danglingAsMissing: GraphNode[] = [...agentRecon.missing, ...placeRecon.missing].map((n) => ({
      id: n.id,
      type: 'missing',
      position: n.position,
      data: { entityId: (n.data.characterId ?? n.data.placeId) as string },
    }));

    const builtEntity = [...persisted, ...danglingAsMissing]
      .map((gn) => toEntityRenderNode(gn, data, onExpandAgent, onExpandPlace, onRemoveMissing))
      .filter((n): n is Node => n !== null);
    const builtPipeline = pipelineGraphNodes.map((gn) => toPipelineRenderNode(gn, pipeline)).filter((n): n is Node => n !== null);
    const builtScratch = scratchGraphNodes.map((gn) => toScratchRenderNode(gn, onImageUpdate, onMusicUpdate)).filter((n): n is Node => n !== null);
    const allBuilt = [...builtEntity, ...builtPipeline, ...builtScratch];

    // Edges referencing a node that didn't make it through (e.g. an
    // agent id that no longer exists and became `missing` under a
    // different id scheme) are dropped -- see the general edge-pruning
    // effect below for the steady-state version of this same rule.
    const nodeIds = new Set(allBuilt.map((n) => n.id));
    const builtEdges = doc.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target)).map(toFlowEdge);

    setNodes(allBuilt);
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
    if (nodes) {
      const graphNodes = nodes.map((n) => entityToGraphNode(n) ?? pipelineToGraphNode(n) ?? scratchToGraphNode(n)).filter((gn): gn is GraphNode => gn !== null);
      save(graphNodes, edges.map(toGraphEdge));
    }
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

  const notOnCanvasAgents = (() => {
    if (!nodes) return [];
    const onCanvasIds = new Set(nodes.filter((n) => n.type === 'agent').map((n) => (n.data as { character: Character }).character.id));
    return data.characters.filter((c) => !onCanvasIds.has(c.id));
  })();
  const notOnCanvasLocations = (() => {
    if (!nodes) return [];
    const onCanvasIds = new Set(nodes.filter((n) => n.type === 'location').map((n) => (n.data as { place: Place }).place.id));
    return data.places.filter((p) => !onCanvasIds.has(p.id));
  })();

  const onDragOver = useCallback((e: DragEvent) => {
    if (!e.dataTransfer.types.includes(DRAG_MIME)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (e: DragEvent) => {
      const payload = e.dataTransfer.getData(DRAG_MIME);
      if (!payload) return;
      e.preventDefault();
      const position = screenToFlowPosition({ x: e.clientX, y: e.clientY });
      const [kind, ...rest] = payload.split(':');
      if (kind === 'pipeline') addPipelineNode(rest[0] as 'sim' | 'treatment' | 'video' | 'text-viewer' | 'frame' | 'storyboard', position);
      else if (kind === 'style' && rest[0] === 'new') addStyleNode(position);
      else if (kind === 'style') addStyleNode(position, styles.find((s) => s.id === rest[0]));
      else if (kind === 'scratch') addScratchNode(rest[0] as 'scratch-image' | 'scratch-music', position);
      else if (kind === 'agent' && rest[0] === 'new') addNewAgent(position);
      else if (kind === 'agent') addToCanvas({ id: rest[0], kind: 'agent' }, position);
      else if (kind === 'location') addToCanvas({ id: rest[0], kind: 'location' }, position);
    },
    [screenToFlowPosition, addPipelineNode, addStyleNode, addScratchNode, addNewAgent, addToCanvas, styles],
  );

  if (!nodes) return <div className="canvas-empty">Loading canvas…</div>;

  const renderNodes = enrichPipelineNodes(nodes, edges, data);

  const sections: DrawerSection[] = [
    {
      id: 'nodes',
      label: 'Nodes',
      items: [
        { id: 'sim', label: 'Simulation', dragPayload: 'pipeline:sim', onAdd: () => addPipelineNode('sim') },
        { id: 'treatment', label: 'Treatment', dragPayload: 'pipeline:treatment', onAdd: () => addPipelineNode('treatment') },
        { id: 'frame', label: 'Frame', dragPayload: 'pipeline:frame', onAdd: () => addPipelineNode('frame') },
        { id: 'storyboard', label: 'Storyboard', dragPayload: 'pipeline:storyboard', onAdd: () => addPipelineNode('storyboard') },
        { id: 'video', label: 'Video', dragPayload: 'pipeline:video', onAdd: () => addPipelineNode('video') },
        { id: 'text-viewer', label: 'Text', sublabel: 'view a Treatment\'s text', dragPayload: 'pipeline:text-viewer', onAdd: () => addPipelineNode('text-viewer') },
        { id: 'image', label: 'Image', dragPayload: 'scratch:scratch-image', onAdd: () => addScratchNode('scratch-image') },
        { id: 'music', label: 'Music', dragPayload: 'scratch:scratch-music', onAdd: () => addScratchNode('scratch-music') },
      ],
    },
    {
      id: 'styles',
      label: 'Styles',
      items: [
        { id: 'new-style', label: '+ New style', dragPayload: 'style:new', onAdd: () => addStyleNode() },
        ...styles.map((s) => ({
          id: s.id,
          label: s.name,
          sublabel: s.style_prompt || undefined,
          dragPayload: `style:${s.id}`,
          onAdd: () => addStyleNode(undefined, s),
          onDelete: () => window.confirm(`Delete style "${s.name}"?`) && removeStyle(s.id).catch((e) => console.error('failed to delete style', e)),
        })),
      ],
    },
    {
      id: 'agents',
      label: 'Agents',
      emptyLabel: 'no other residents to add',
      items: [
        { id: 'new-agent', label: '+ New agent', sublabel: 'generate a resident', dragPayload: 'agent:new', onAdd: () => addNewAgent() },
        ...notOnCanvasAgents.map((c) => ({ id: c.id, label: c.name, sublabel: c.occupation, dragPayload: `agent:${c.id}`, onAdd: () => addToCanvas({ id: c.id, kind: 'agent' }) })),
      ],
    },
    {
      id: 'locations',
      label: 'Locations',
      emptyLabel: 'every place is already on canvas',
      items: notOnCanvasLocations.map((p) => ({ id: p.id, label: p.name, sublabel: p.place_type, dragPayload: `location:${p.id}`, onAdd: () => addToCanvas({ id: p.id, kind: 'location' }) })),
    },
  ];

  return (
    <div className="city-canvas-layout">
      <SideDrawer sections={sections} />
      <div className="canvas-with-tray" onDragOver={onDragOver} onDrop={onDrop}>
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
          <MiniMap nodeColor={miniMapNodeColor} pannable zoomable />
        </ReactFlow>
      </div>
      <Inspector selection={selection} data={data} onDataRefresh={onDataRefresh} />
      {newAgentModal && (
        <NewAgentModal
          places={data.places}
          onClose={() => setNewAgentModal(null)}
          onCreated={(character) => {
            placeAgentNode(character, newAgentModal.position);
            setNewAgentModal(null);
          }}
        />
      )}
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
      <CanvasInner cityId={cityId} data={data} onDataRefresh={load} />
    </ReactFlowProvider>
  );
}
