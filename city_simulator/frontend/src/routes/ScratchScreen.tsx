import { useCallback, useEffect, useRef, useState } from 'react';
import type { DragEvent } from 'react';
import type { Connection, Edge, Node } from '@xyflow/react';
import { addEdge, applyEdgeChanges, applyNodeChanges, Background, BackgroundVariant, Controls, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { history } from '../api/client';
import type { Character, GraphNode, HistoryData, Place } from '../api/types';
import '../flow/canvas.css';
import { isValidConnection as checkValidConnection } from '../flow/edgeRules';
import { entityToGraphNode, toEntityRenderNode } from '../flow/entityNodeKit';
import { toFlowEdge, toGraphEdge } from '../flow/graphIds';
import { miniMapNodeColor } from '../flow/miniMapColor';
import { AgentNode } from '../flow/nodes/AgentNode';
import { FrameNode } from '../flow/nodes/FrameNode';
import { LocationNode } from '../flow/nodes/LocationNode';
import { MissingNode } from '../flow/nodes/MissingNode';
import { ScratchImageNode, type ScratchImageNodeData } from '../flow/nodes/ScratchImageNode';
import { ScratchMusicNode, type ScratchMusicNodeData } from '../flow/nodes/ScratchMusicNode';
import { SimulationNode } from '../flow/nodes/SimulationNode';
import { StyleNode } from '../flow/nodes/StyleNode';
import { TreatmentNode } from '../flow/nodes/TreatmentNode';
import { VideoNode } from '../flow/nodes/VideoNode';
import { enrichPipelineNodes, pipelineToGraphNode, toPipelineRenderNode } from '../flow/pipeline';
import { reconcile } from '../flow/reconcile';
import { scratchToGraphNode, toScratchRenderNode } from '../flow/scratchNodeKit';
import { DRAG_MIME, SideDrawer, type DrawerSection } from '../flow/SideDrawer';
import { useAddNodeActions } from '../flow/useAddNodeActions';
import { usePersistedGraph } from '../flow/usePersistedGraph';
import { usePipelineCallbacks } from '../flow/usePipelineCallbacks';

const nodeTypes = {
  agent: AgentNode,
  location: LocationNode,
  missing: MissingNode,
  sim: SimulationNode,
  treatment: TreatmentNode,
  frame: FrameNode,
  video: VideoNode,
  style: StyleNode,
  'scratch-image': ScratchImageNode,
  'scratch-music': ScratchMusicNode,
};

const PIPELINE_TYPES = new Set(['sim', 'treatment', 'frame', 'video', 'style']);
const SCRATCH_TYPES = new Set(['scratch-image', 'scratch-music']);

// A Scratch board still has the full node palette (Agent/Location/
// Simulation/Treatment/Frame/Video), not just Style/Image/Music -- it's
// "ungrounded" in that it doesn't belong to any one city, but it can
// still reference whichever city happens to be active, same as opening
// any other tab would show. If nothing's ever been generated, the
// Agents/Locations sections are just honestly empty.
function ScratchCanvasInner({ boardId, cityData }: { boardId: string; cityData: HistoryData | null }) {
  const { doc, save } = usePersistedGraph(`scratch:${boardId}`);
  const { screenToFlowPosition } = useReactFlow();
  const [nodes, setNodes] = useState<Node[] | null>(null);
  const [edges, setEdges] = useState<Edge[]>([]);
  const initializedFor = useRef<string | null>(null);

  const onImageUpdate = useCallback((nodeId: string, patch: Partial<ScratchImageNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);
  const onMusicUpdate = useCallback((nodeId: string, patch: Partial<ScratchMusicNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);
  // No navigation from a scratch board -- Agent/Location nodes here are
  // reference/context for wiring into a Simulation, not a way to drill
  // into that entity's own screen.
  const noExpand = useCallback(() => {}, []);
  const onRemoveMissing = useCallback((nodeId: string) => {
    setNodes((prev) => (prev ? prev.filter((n) => n.id !== nodeId) : prev));
    setEdges((prev) => prev.filter((e) => e.source !== nodeId && e.target !== nodeId));
  }, []);

  const pipeline = usePipelineCallbacks(setNodes, setEdges);
  const { addToCanvas, addPipelineNode, addStyleNode, addNewAgent, addScratchNode } = useAddNodeActions({
    data: cityData,
    setNodes,
    onExpandAgent: noExpand,
    onExpandPlace: noExpand,
    onRemoveMissing,
    pipeline,
    onImageUpdate,
    onMusicUpdate,
  });

  // No media/entity reconciliation the way CityCanvas/EntityCanvas need
  // (scratch-image/scratch-music's own data IS their entire state), but
  // Agent/Location nodes dropped here DO reference real ids and need the
  // same reconciliation as everywhere else once cityData is known.
  useEffect(() => {
    if (!doc) return;
    const agentIds = cityData?.characters.map((c) => c.id) ?? [];
    const placeIds = cityData?.places.map((p) => p.id) ?? [];
    const key = `${doc.rev}:${cityData?.generated_at ?? 'none'}`;
    if (initializedFor.current === key && nodes) return;
    initializedFor.current = key;

    const agentRecon = reconcile(doc.nodes.filter((n) => n.type === 'agent'), agentIds, (n) => n.data.characterId as string);
    const placeRecon = reconcile(doc.nodes.filter((n) => n.type === 'location'), placeIds, (n) => n.data.placeId as string);
    const alreadyMissing = doc.nodes.filter((n) => n.type === 'missing');
    const danglingAsMissing: GraphNode[] = [...agentRecon.missing, ...placeRecon.missing].map((n) => ({
      id: n.id,
      type: 'missing',
      position: n.position,
      data: { entityId: (n.data.characterId ?? n.data.placeId) as string },
    }));
    const builtEntity = cityData
      ? [...agentRecon.present, ...placeRecon.present, ...alreadyMissing, ...danglingAsMissing]
          .map((gn) => toEntityRenderNode(gn, cityData, noExpand, noExpand, onRemoveMissing))
          .filter((n): n is Node => n !== null)
      : [];

    const pipelineGraphNodes = doc.nodes.filter((n) => PIPELINE_TYPES.has(n.type));
    const builtPipeline = cityData ? pipelineGraphNodes.map((gn) => toPipelineRenderNode(gn, cityData, pipeline)).filter((n): n is Node => n !== null) : [];

    const scratchGraphNodes = doc.nodes.filter((n) => SCRATCH_TYPES.has(n.type));
    const builtScratch = scratchGraphNodes.map((gn) => toScratchRenderNode(gn, onImageUpdate, onMusicUpdate)).filter((n): n is Node => n !== null);

    const allBuilt = [...builtEntity, ...builtPipeline, ...builtScratch];
    const nodeIds = new Set(allBuilt.map((n) => n.id));
    setNodes(allBuilt);
    setEdges(doc.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target)).map(toFlowEdge));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, cityData]);

  // Prune edges whenever a node disappears (delete key on a selected
  // node) -- without this, an edge could keep pointing at a removed
  // node's id forever.
  useEffect(() => {
    if (!nodes) return;
    const ids = new Set(nodes.map((n) => n.id));
    setEdges((prev) => prev.filter((e) => ids.has(e.source) && ids.has(e.target)));
  }, [nodes]);

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

  const notOnCanvasAgents = (() => {
    if (!nodes || !cityData) return [];
    const onCanvasIds = new Set(nodes.filter((n) => n.type === 'agent').map((n) => (n.data as { character: Character }).character.id));
    return cityData.characters.filter((c) => !onCanvasIds.has(c.id));
  })();
  const notOnCanvasLocations = (() => {
    if (!nodes || !cityData) return [];
    const onCanvasIds = new Set(nodes.filter((n) => n.type === 'location').map((n) => (n.data as { place: Place }).place.id));
    return cityData.places.filter((p) => !onCanvasIds.has(p.id));
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
      if (kind === 'scratch') addScratchNode(rest[0] as 'scratch-image' | 'scratch-music', position);
      else if (kind === 'style') addStyleNode(position);
      else if (kind === 'pipeline') addPipelineNode(rest[0] as 'sim' | 'treatment' | 'video', position);
      else if (kind === 'agent' && rest[0] === 'new') addNewAgent(position);
      else if (kind === 'agent') addToCanvas({ id: rest[0], kind: 'agent' }, position);
      else if (kind === 'location') addToCanvas({ id: rest[0], kind: 'location' }, position);
    },
    [screenToFlowPosition, addScratchNode, addStyleNode, addPipelineNode, addNewAgent, addToCanvas],
  );

  if (!nodes) return <div className="canvas-empty">Loading canvas…</div>;

  const renderNodes = cityData ? enrichPipelineNodes(nodes, edges, cityData) : nodes;

  const sections: DrawerSection[] = [
    {
      id: 'nodes',
      label: 'Nodes',
      items: [
        { id: 'image', label: '+ Image', dragPayload: 'scratch:scratch-image', onAdd: () => addScratchNode('scratch-image') },
        { id: 'music', label: '+ Music', dragPayload: 'scratch:scratch-music', onAdd: () => addScratchNode('scratch-music') },
        { id: 'style', label: '+ Style', dragPayload: 'style:new', onAdd: () => addStyleNode() },
        { id: 'sim', label: 'Simulation', dragPayload: 'pipeline:sim', onAdd: () => addPipelineNode('sim') },
        { id: 'treatment', label: 'Treatment', dragPayload: 'pipeline:treatment', onAdd: () => addPipelineNode('treatment') },
        { id: 'video', label: 'Video', dragPayload: 'pipeline:video', onAdd: () => addPipelineNode('video') },
      ],
    },
    {
      id: 'agents',
      label: 'Agents',
      emptyLabel: cityData ? 'no other residents to add' : 'no active city',
      items: [
        { id: 'new-agent', label: '+ New agent', sublabel: 'generate a resident', dragPayload: 'agent:new', onAdd: () => addNewAgent() },
        ...notOnCanvasAgents.map((c) => ({ id: c.id, label: c.name, sublabel: c.occupation, dragPayload: `agent:${c.id}`, onAdd: () => addToCanvas({ id: c.id, kind: 'agent' }) })),
      ],
    },
    {
      id: 'locations',
      label: 'Locations',
      emptyLabel: cityData ? 'every place is already on canvas' : 'no active city',
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
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} color="var(--canvas-dot)" />
          <Controls showInteractive={false} />
          <MiniMap nodeColor={miniMapNodeColor} pannable zoomable />
        </ReactFlow>
      </div>
    </div>
  );
}

export function ScratchScreen({ boardId }: { boardId: string }) {
  const [cityData, setCityData] = useState<HistoryData | null>(null);

  useEffect(() => {
    history.data().then(setCityData).catch(() => setCityData(null));
  }, []);

  return (
    <ReactFlowProvider>
      <ScratchCanvasInner boardId={boardId} cityData={cityData} />
    </ReactFlowProvider>
  );
}
