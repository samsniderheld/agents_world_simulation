import { useCallback, useEffect, useRef, useState, Fragment } from 'react';
import type { DragEvent } from 'react';
import type { Connection, Edge, Node, NodeMouseHandler, XYPosition } from '@xyflow/react';
import { addEdge, applyEdgeChanges, applyNodeChanges, Background, BackgroundVariant, Controls, MiniMap, ReactFlow, ReactFlowProvider, useReactFlow } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { city } from '../api/client';
import type { Character, GraphNode, HistoryData, MediaItem, Place } from '../api/types';
import './canvas.css';
import { isValidConnection as checkValidConnection } from './edgeRules';
import { entityToGraphNode, toEntityRenderNode } from './entityNodeKit';
import { NewAgentModal } from './NewAgentModal';
import { AgentNode } from './nodes/AgentNode';
import { FrameNode } from './nodes/FrameNode';
import { ImageNode, type ImageNodeData } from './nodes/ImageNode';
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
import { gridPosition } from './layout';
import { miniMapNodeColor } from './miniMapColor';
import { enrichPipelineNodes, pipelineToGraphNode, toPipelineRenderNode } from './pipeline';
import { toFlowEdge, toGraphEdge } from './graphIds';
import { reconcile } from './reconcile';
import { navigate, type Scope } from '../routes/router';
import { scratchToGraphNode, toScratchRenderNode } from './scratchNodeKit';
import { useAddNodeActions } from './useAddNodeActions';
import { useHiddenEntities } from './useHiddenEntities';
import { usePersistedGraph } from './usePersistedGraph';
import { usePipelineCallbacks } from './usePipelineCallbacks';
import { useStylesLibrary } from './useStylesLibrary';

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
  image: ImageNode,
  'scratch-image': ScratchImageNode,
  'scratch-music': ScratchMusicNode,
};

const PIPELINE_TYPES = new Set(['sim', 'treatment', 'frame', 'video', 'style', 'storyboard', 'text-viewer']);
const SCRATCH_TYPES = new Set(['scratch-image', 'scratch-music']);

function toImageRenderNode(gn: GraphNode, entityId: string, mediaById: Map<string, MediaItem>, onUpdate: ImageNodeData['onUpdate']): Node | null {
  if (gn.type !== 'image') return null;
  const mediaId = gn.data.mediaId as string | undefined;
  const media = mediaId ? mediaById.get(mediaId) : undefined;
  if (mediaId && !media) return null; // already routed to `missing` by the caller
  return {
    id: gn.id,
    type: 'image',
    position: gn.position,
    // Same explicit floor as Frame/Video's own render-node builders (see
    // pipeline.ts) -- without it a never-resized Image node shrink-to-
    // fits its own content independently of its siblings.
    width: gn.width ?? 540,
    height: gn.height ?? 430,
    data: { entityId, prompt: (gn.data.prompt as string) ?? media?.prompt ?? '', mediaId, mediaUrl: media ? city.fileUrl(media.url) : undefined, onUpdate },
  };
}

function imageToGraphNode(n: Node): GraphNode | null {
  if (n.type !== 'image') return null;
  const d = n.data as ImageNodeData;
  return { id: n.id, type: 'image', position: n.position, width: n.width, height: n.height, data: { prompt: d.prompt, mediaId: d.mediaId } };
}

// This entity's own drill-in canvas, with the *same* full node palette
// every other canvas offers (Agent/Location/Simulation/Treatment/Frame/
// Video/Style/Image/Music) -- not scoped down to "just images," per the
// requirement that no node type be tied to wherever it happened to make
// the most obvious sense. `cityData` (this entity's own city) drives the
// Agents/Locations sections and reconciliation exactly like CityCanvas;
// `entityId` is additionally the *default* target new Image/Frame nodes
// attach their media to, since that's still the natural default here.
function CanvasInner({
  cityId,
  entityId,
  scope,
  media,
  cityData,
  onCityDataRefresh,
}: {
  cityId?: string;
  entityId: string;
  scope: string;
  media: MediaItem[];
  cityData: HistoryData | null;
  onCityDataRefresh?: () => void;
}) {
  const { doc, save } = usePersistedGraph(scope);
  const { screenToFlowPosition } = useReactFlow();
  const [nodes, setNodes] = useState<Node[] | null>(null);
  const [edges, setEdges] = useState<Edge[]>([]);
  const initializedFor = useRef<string | null>(null);

  // Same "refresh after a real generation" rule usePipelineCallbacks
  // applies to Frame/Video -- this canvas's standalone `image` node type
  // isn't part of that shared hook, so it needs its own copy of the same
  // fix: without it, any OTHER node whose agent:in/place:in reference
  // images come from *this* entity's media would keep working off a
  // stale snapshot that doesn't yet include what was just generated.
  const onImageUpdate = useCallback(
    (nodeId: string, patch: Partial<ImageNodeData>) => {
      setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
      if (patch.mediaId) onCityDataRefresh?.();
    },
    [onCityDataRefresh],
  );
  const onScratchImageUpdate = useCallback((nodeId: string, patch: Partial<ScratchImageNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);
  const onMusicUpdate = useCallback((nodeId: string, patch: Partial<ScratchMusicNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);
  // No navigation from here (an entity's own canvas doesn't drill into
  // yet another entity) -- Agent/Location nodes dropped here are purely
  // reference/context, so onExpand is a no-op rather than another route.
  const noExpand = useCallback(() => {}, []);
  const onRemoveMissing = useCallback((nodeId: string) => {
    setNodes((prev) => (prev ? prev.filter((n) => n.id !== nodeId) : prev));
    setEdges((prev) => prev.filter((e) => e.source !== nodeId && e.target !== nodeId));
  }, []);

  // Both AgentScreen and PlaceScreen route through this same canvas,
  // distinguished only by their own `scope` string's prefix (see how
  // AgentScreen/PlaceScreen call EntityCanvas) -- reused here to rebuild
  // which one this entity's own screen actually is, so "up one level"
  // goes back to it rather than the root Cities list.
  const onExpandStoryboard = useCallback(
    (storyboardId: string) => {
      const from: Scope | undefined =
        cityId && scope.startsWith('agent:')
          ? { kind: 'agent', cityId, agentId: entityId }
          : cityId && scope.startsWith('place:')
            ? { kind: 'place', cityId, placeId: entityId }
            : undefined;
      navigate({ kind: 'storyboard', storyboardId, from });
    },
    [cityId, entityId, scope],
  );
  const pipeline = usePipelineCallbacks(setNodes, setEdges, onExpandStoryboard);
  const { isHidden } = useHiddenEntities(cityId);
  const { styles, refresh: refreshStyles, remove: removeStyle } = useStylesLibrary();
  const [newAgentModal, setNewAgentModal] = useState<{ position?: XYPosition } | null>(null);
  const { addToCanvas, addPipelineNode, addStyleNode, addNewAgent, placeAgentNode, addScratchNode } = useAddNodeActions({
    data: cityData,
    setNodes,
    onExpandAgent: noExpand,
    onExpandPlace: noExpand,
    onRemoveMissing,
    onDataRefresh: onCityDataRefresh,
    onStyleCreated: refreshStyles,
    onOpenNewAgentModal: (position) => setNewAgentModal({ position }),
    pipeline,
    onImageUpdate: onScratchImageUpdate,
    onMusicUpdate,
  });

  const addImageNode = useCallback(
    (position?: XYPosition) => {
      setNodes((prev) => {
        const list = prev ?? [];
        const pos = position ?? gridPosition(list.length, { columns: 4, cellWidth: 260, cellHeight: 220 });
        const id = `image:draft_${Date.now()}`;
        return [...list, { id, type: 'image', position: pos, data: { entityId, prompt: '', onUpdate: onImageUpdate } }];
      });
    },
    [entityId, onImageUpdate],
  );

  useEffect(() => {
    if (!doc || !cityData) return;
    const images = media.filter((m) => m.kind === 'image');
    const mediaIds = images.map((m) => m.id);
    const mediaById = new Map(images.map((m) => [m.id, m]));
    const agentIds = cityData.characters.map((c) => c.id);
    const placeIds = cityData.places.map((p) => p.id);
    // Deliberately NOT keyed on mediaIds -- usePersistedGraph's `doc` is
    // frozen at whatever it was on mount/scope-change (it's never updated
    // after an autosave, see that hook's own comment on why), so any node
    // added or resized *after* mount is already missing from doc.nodes.
    // Rebuilding from `doc` every time `media` changes (which
    // onCityDataRefresh does after every completed generation, per
    // ImageNode/FrameNode/VideoNode's onUpdate) would silently wipe every
    // such node back out on the very first image a user generates here --
    // confirmed live: a Style node + an Image node, added this session,
    // both vanished the moment the image finished. The one-time initial
    // reconciliation this effect exists for still happens (doc/cityData
    // change on real mount or a rev conflict), just not on every media
    // refresh in between.
    const key = `${doc.rev}:${cityData.generated_at}`;
    if (initializedFor.current === key && nodes) return;
    initializedFor.current = key;

    const imageGraphNodes = doc.nodes.filter((n) => n.type === 'image');
    // Draft image nodes (never generated -- no mediaId yet) don't
    // reference anything, so they're always kept; only generated ones
    // reconcile against the entity's current media.
    const imageDrafts = imageGraphNodes.filter((n) => !n.data.mediaId);
    const imageGenerated = imageGraphNodes.filter((n) => n.data.mediaId);
    const imageRecon = reconcile(imageGenerated, mediaIds, (n) => n.data.mediaId as string);
    const builtImages = [...imageDrafts, ...imageRecon.present]
      .map((gn) => toImageRenderNode(gn, entityId, mediaById, onImageUpdate))
      .filter((n): n is Node => n !== null);
    // An image node whose media was deleted is low-value clutter here --
    // dropped rather than rendered as `missing`, same call as before.

    const agentRecon = reconcile(doc.nodes.filter((n) => n.type === 'agent'), agentIds, (n) => n.data.characterId as string);
    const placeRecon = reconcile(doc.nodes.filter((n) => n.type === 'location'), placeIds, (n) => n.data.placeId as string);
    const alreadyMissing = doc.nodes.filter((n) => n.type === 'missing');
    const danglingAsMissing: GraphNode[] = [...agentRecon.missing, ...placeRecon.missing].map((n) => ({
      id: n.id,
      type: 'missing',
      position: n.position,
      data: { entityId: (n.data.characterId ?? n.data.placeId) as string },
    }));
    const builtEntity = [...agentRecon.present, ...placeRecon.present, ...alreadyMissing, ...danglingAsMissing]
      .map((gn) => toEntityRenderNode(gn, cityData, noExpand, noExpand, onRemoveMissing))
      .filter((n): n is Node => n !== null);

    const pipelineGraphNodes = doc.nodes.filter((n) => PIPELINE_TYPES.has(n.type));
    const builtPipeline = pipelineGraphNodes.map((gn) => toPipelineRenderNode(gn, pipeline)).filter((n): n is Node => n !== null);

    const scratchGraphNodes = doc.nodes.filter((n) => SCRATCH_TYPES.has(n.type));
    const builtScratch = scratchGraphNodes.map((gn) => toScratchRenderNode(gn, onScratchImageUpdate, onMusicUpdate)).filter((n): n is Node => n !== null);

    const allBuilt = [...builtImages, ...builtEntity, ...builtPipeline, ...builtScratch];
    const nodeIds = new Set(allBuilt.map((n) => n.id));
    const builtEdges = doc.edges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target)).map(toFlowEdge);

    setNodes(allBuilt);
    setEdges(builtEdges);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, media, cityData, entityId]);

  useEffect(() => {
    if (!nodes) return;
    const ids = new Set(nodes.map((n) => n.id));
    setEdges((prev) => prev.filter((e) => ids.has(e.source) && ids.has(e.target)));
  }, [nodes]);

  useEffect(() => {
    if (nodes) {
      const graphNodes = nodes
        .map((n) => imageToGraphNode(n) ?? entityToGraphNode(n) ?? pipelineToGraphNode(n) ?? scratchToGraphNode(n))
        .filter((gn): gn is GraphNode => gn !== null);
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
  // Nothing to navigate to from here (see noExpand above) -- clicks just
  // don't do anything special, unlike CityCanvas's onNodeClick/dblclick.
  const onNodeClick: NodeMouseHandler = useCallback(() => {}, []);

  const notOnCanvasMedia = (() => {
    if (!nodes) return [];
    const onCanvasMediaIds = new Set(nodes.filter((n) => n.type === 'image').map((n) => (n.data as ImageNodeData).mediaId).filter(Boolean));
    return media.filter((m) => m.kind === 'image' && !onCanvasMediaIds.has(m.id));
  })();
  const notOnCanvasAgents = (() => {
    if (!nodes || !cityData) return [];
    const onCanvasIds = new Set(nodes.filter((n) => n.type === 'agent').map((n) => (n.data as { character: Character }).character.id));
    return cityData.characters.filter((c) => !onCanvasIds.has(c.id) && !isHidden(c.id));
  })();
  const notOnCanvasLocations = (() => {
    if (!nodes || !cityData) return [];
    const onCanvasIds = new Set(nodes.filter((n) => n.type === 'location').map((n) => (n.data as { place: Place }).place.id));
    return cityData.places.filter((p) => !onCanvasIds.has(p.id) && !isHidden(p.id));
  })();

  const addExistingMedia = useCallback(
    (mediaId: string, position?: XYPosition) => {
      const item = media.find((m) => m.id === mediaId);
      if (!item) return;
      setNodes((prev) => {
        const list = prev ?? [];
        const pos = position ?? gridPosition(list.length, { columns: 4, cellWidth: 260, cellHeight: 220 });
        const built = toImageRenderNode({ id: `image:${item.id}`, type: 'image', position: pos, data: { mediaId: item.id } }, entityId, new Map([[item.id, item]]), onImageUpdate);
        return built ? [...list, built] : list;
      });
    },
    [media, entityId, onImageUpdate],
  );

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
      if (kind === 'image' && rest[0] === 'new') addImageNode(position);
      else if (kind === 'media') addExistingMedia(rest[0], position);
      else if (kind === 'pipeline') addPipelineNode(rest[0] as 'sim' | 'treatment' | 'video' | 'text-viewer' | 'frame' | 'storyboard', position);
      else if (kind === 'style' && rest[0] === 'new') addStyleNode(position);
      else if (kind === 'style') addStyleNode(position, styles.find((s) => s.id === rest[0]));
      else if (kind === 'scratch') addScratchNode(rest[0] as 'scratch-image' | 'scratch-music', position);
      else if (kind === 'agent' && rest[0] === 'new') addNewAgent(position);
      else if (kind === 'agent') addToCanvas({ id: rest[0], kind: 'agent' }, position);
      else if (kind === 'location') addToCanvas({ id: rest[0], kind: 'location' }, position);
    },
    [screenToFlowPosition, addImageNode, addExistingMedia, addPipelineNode, addStyleNode, addScratchNode, addNewAgent, addToCanvas, styles],
  );

  if (!nodes) return <div className="canvas-empty">Loading canvas…</div>;

  const renderNodes = cityData ? enrichPipelineNodes(nodes, edges, cityData) : nodes;

  const sections: DrawerSection[] = [
    {
      id: 'nodes',
      label: 'Nodes',
      items: [
        { id: 'new-image', label: '+ Image', dragPayload: 'image:new', onAdd: () => addImageNode() },
        { id: 'sim', label: 'Simulation', dragPayload: 'pipeline:sim', onAdd: () => addPipelineNode('sim') },
        { id: 'treatment', label: 'Treatment', dragPayload: 'pipeline:treatment', onAdd: () => addPipelineNode('treatment') },
        { id: 'frame', label: 'Frame', dragPayload: 'pipeline:frame', onAdd: () => addPipelineNode('frame') },
        { id: 'storyboard', label: 'Storyboard', dragPayload: 'pipeline:storyboard', onAdd: () => addPipelineNode('storyboard') },
        { id: 'video', label: 'Video', dragPayload: 'pipeline:video', onAdd: () => addPipelineNode('video') },
        { id: 'text-viewer', label: 'Text', sublabel: 'view a Treatment\'s text', dragPayload: 'pipeline:text-viewer', onAdd: () => addPipelineNode('text-viewer') },
        { id: 'scratch-image', label: 'Freeform image', dragPayload: 'scratch:scratch-image', onAdd: () => addScratchNode('scratch-image') },
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
      emptyLabel: cityId ? 'no other residents to add' : 'no city context',
      items: [
        { id: 'new-agent', label: '+ New agent', sublabel: 'generate a resident', dragPayload: 'agent:new', onAdd: () => addNewAgent() },
        ...notOnCanvasAgents.map((c) => ({ id: c.id, label: c.name, sublabel: c.occupation, dragPayload: `agent:${c.id}`, onAdd: () => addToCanvas({ id: c.id, kind: 'agent' }) })),
      ],
    },
    {
      id: 'locations',
      label: 'Locations',
      emptyLabel: cityId ? 'every place is already on canvas' : 'no city context',
      items: notOnCanvasLocations.map((p) => ({ id: p.id, label: p.name, sublabel: p.place_type, dragPayload: `location:${p.id}`, onAdd: () => addToCanvas({ id: p.id, kind: 'location' }) })),
    },
    {
      id: 'media',
      label: 'Existing media',
      emptyLabel: 'nothing generated yet',
      items: notOnCanvasMedia.map((m) => ({ id: m.id, label: m.prompt.slice(0, 40) || m.id, dragPayload: `media:${m.id}`, onAdd: () => addExistingMedia(m.id) })),
    },
  ];

  // A fragment, not another .city-canvas-layout wrapper -- the caller
  // (AgentScreen/PlaceScreen) already provides that flex row, alongside
  // its own Inspector; nesting a second flex container here would break
  // that outer layout instead of composing with it.
  return (
    <Fragment>
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
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} color="var(--canvas-dot)" />
          <Controls showInteractive={false} />
          <MiniMap nodeColor={miniMapNodeColor} pannable zoomable />
        </ReactFlow>
      </div>
      {newAgentModal && cityData && (
        <NewAgentModal
          places={cityData.places}
          onClose={() => setNewAgentModal(null)}
          onCreated={(character) => {
            placeAgentNode(character, newAgentModal.position);
            setNewAgentModal(null);
          }}
        />
      )}
    </Fragment>
  );
}

export function EntityCanvas(props: { cityId?: string; entityId: string; scope: string; media: MediaItem[]; cityData: HistoryData | null; onCityDataRefresh?: () => void }) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}
