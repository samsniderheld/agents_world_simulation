import { useCallback, useEffect, useRef, useState } from 'react';
import type { Node } from '@xyflow/react';
import { applyNodeChanges, Background, BackgroundVariant, Controls, Panel, ReactFlow, ReactFlowProvider } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { city } from '../api/client';
import type { GraphNode, MediaItem } from '../api/types';
import './canvas.css';
import { gridPosition } from './layout';
import { ImageNode, type ImageNodeData } from './nodes/ImageNode';
import { NotOnCanvasTray } from './NotOnCanvasTray';
import { reconcile } from './reconcile';
import { usePersistedGraph } from './usePersistedGraph';

const nodeTypes = { image: ImageNode };

function toRenderNode(gn: GraphNode, entityId: string, mediaById: Map<string, MediaItem>, onUpdate: ImageNodeData['onUpdate']): Node | null {
  if (gn.type !== 'image') return null;
  const mediaId = gn.data.mediaId as string | undefined;
  const media = mediaId ? mediaById.get(mediaId) : undefined;
  if (mediaId && !media) return null; // already routed to `missing` by the caller
  return {
    id: gn.id,
    type: 'image',
    position: gn.position,
    data: {
      entityId,
      prompt: (gn.data.prompt as string) ?? media?.prompt ?? '',
      mediaId,
      mediaUrl: media ? city.fileUrl(media.url) : undefined,
      onUpdate,
    },
  };
}

function toGraphNode(n: Node): GraphNode {
  const d = n.data as ImageNodeData;
  return { id: n.id, type: 'image', position: n.position, data: { prompt: d.prompt, mediaId: d.mediaId } };
}

// Shared between the Agent and Location drill-in screens -- both are
// "this entity's own generation canvas," differing only in which entity
// id media attaches to. Video nodes and the shot/style pipeline wiring
// are Phase 3 (once Simulation/Treatment/Frame nodes exist to connect
// to); this is deliberately just the image side for now, the node-ified
// version of the old app's "+ Media" button.
function CanvasInner({ entityId, scope, media }: { entityId: string; scope: string; media: MediaItem[] }) {
  const { doc, save } = usePersistedGraph(scope);
  const [nodes, setNodes] = useState<Node[] | null>(null);
  const initializedFor = useRef<string | null>(null);

  const onUpdate = useCallback<ImageNodeData['onUpdate']>((nodeId, patch) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);

  useEffect(() => {
    if (!doc) return;
    const images = media.filter((m) => m.kind === 'image');
    const mediaIds = images.map((m) => m.id);
    const mediaById = new Map(images.map((m) => [m.id, m]));
    const key = `${doc.rev}:${mediaIds.join(',')}`;
    if (initializedFor.current === key && nodes) return;
    initializedFor.current = key;

    const imageGraphNodes = doc.nodes.filter((n) => n.type === 'image');
    // Draft nodes (never generated -- no mediaId yet) don't reference
    // anything, so they're always kept; only generated ones reconcile
    // against the entity's current media.
    const drafts = imageGraphNodes.filter((n) => !n.data.mediaId);
    const generated = imageGraphNodes.filter((n) => n.data.mediaId);
    const recon = reconcile(generated, mediaIds, (n) => n.data.mediaId as string);

    const built = [...drafts, ...recon.present]
      .map((gn) => toRenderNode(gn, entityId, mediaById, onUpdate))
      .filter((n): n is Node => n !== null);
    // A `missing` image node (its media deleted) is low-value clutter --
    // unlike an Agent/Location node's regenerate-orphaned reference,
    // there's no larger arrangement worth preserving here, so these are
    // just dropped rather than rendered as dimmed placeholders.

    setNodes(built);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc, media]);

  useEffect(() => {
    if (nodes) save(nodes.map(toGraphNode), []);
  }, [nodes, save]);

  const onNodesChange = useCallback((changes: Parameters<typeof applyNodeChanges>[0]) => {
    setNodes((nds) => (nds ? applyNodeChanges(changes, nds) : nds));
  }, []);

  const notOnCanvas = (() => {
    if (!nodes) return [];
    const onCanvasMediaIds = new Set(nodes.map((n) => (n.data as ImageNodeData).mediaId).filter(Boolean));
    return media.filter((m) => m.kind === 'image' && !onCanvasMediaIds.has(m.id)).map((m) => ({ id: m.id, label: m.prompt.slice(0, 40) || m.id }));
  })();

  const addExisting = useCallback(
    (entry: { id: string }) => {
      const item = media.find((m) => m.id === entry.id);
      if (!item) return;
      setNodes((prev) => {
        const list = prev ?? [];
        const position = gridPosition(list.length, { columns: 4, cellWidth: 260, cellHeight: 220 });
        const built = toRenderNode({ id: `image:${item.id}`, type: 'image', position, data: { mediaId: item.id } }, entityId, new Map([[item.id, item]]), onUpdate);
        return built ? [...list, built] : list;
      });
    },
    [media, entityId, onUpdate],
  );

  const addDraft = useCallback(() => {
    setNodes((prev) => {
      const list = prev ?? [];
      const position = gridPosition(list.length, { columns: 4, cellWidth: 260, cellHeight: 220 });
      const id = `image:draft_${Date.now()}`;
      return [...list, { id, type: 'image', position, data: { entityId, prompt: '', onUpdate } }];
    });
  }, [entityId, onUpdate]);

  if (!nodes) return <div className="canvas-empty">Loading canvas…</div>;

  return (
    <div className="canvas-with-tray">
      <ReactFlow nodes={nodes} edges={[]} nodeTypes={nodeTypes} onNodesChange={onNodesChange} fitView proOptions={{ hideAttribution: true }}>
        <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} color="var(--canvas-dot)" />
        <Controls showInteractive={false} />
        <Panel position="top-right">
          <button className="node-run-btn" style={{ flex: 'none', padding: '6px 12px' }} onClick={addDraft}>
            + Image node
          </button>
        </Panel>
      </ReactFlow>
      <NotOnCanvasTray entries={notOnCanvas} onAdd={addExisting} />
    </div>
  );
}

export function EntityCanvas(props: { entityId: string; scope: string; media: MediaItem[] }) {
  return (
    <ReactFlowProvider>
      <CanvasInner {...props} />
    </ReactFlowProvider>
  );
}
