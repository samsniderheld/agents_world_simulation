import { useCallback, useEffect, useRef, useState } from 'react';
import type { Connection, Edge, Node } from '@xyflow/react';
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
import { stylesApi } from '../api/client';
import type { GraphNode, Style } from '../api/types';
import '../flow/canvas.css';
import { isValidConnection as checkValidConnection } from '../flow/edgeRules';
import { newNodeId, toFlowEdge, toGraphEdge } from '../flow/graphIds';
import { gridPosition } from '../flow/layout';
import { ScratchImageNode, type ScratchImageNodeData } from '../flow/nodes/ScratchImageNode';
import { ScratchMusicNode, type ScratchMusicNodeData } from '../flow/nodes/ScratchMusicNode';
import { StyleNode, type StyleNodeData } from '../flow/nodes/StyleNode';
import { usePersistedGraph } from '../flow/usePersistedGraph';

const nodeTypes = { 'scratch-image': ScratchImageNode, 'scratch-music': ScratchMusicNode, style: StyleNode };

interface Callbacks {
  onImageUpdate: (nodeId: string, patch: Partial<ScratchImageNodeData>) => void;
  onMusicUpdate: (nodeId: string, patch: Partial<ScratchMusicNodeData>) => void;
  onStyleLoaded: (nodeId: string, style: Style) => void;
  onStyleUpdate: (nodeId: string, patch: Partial<Style>) => void;
}

function toRenderNode(gn: GraphNode, cb: Callbacks): Node | null {
  if (gn.type === 'scratch-image') {
    return {
      id: gn.id,
      type: 'scratch-image',
      position: gn.position,
      data: { prompt: (gn.data.prompt as string) ?? '', url: gn.data.url as string | undefined, localPath: gn.data.localPath as string | undefined, onUpdate: cb.onImageUpdate },
    };
  }
  if (gn.type === 'scratch-music') {
    return {
      id: gn.id,
      type: 'scratch-music',
      position: gn.position,
      data: {
        prompt: (gn.data.prompt as string) ?? '',
        negativePrompt: (gn.data.negativePrompt as string) ?? '',
        url: gn.data.url as string | undefined,
        onUpdate: cb.onMusicUpdate,
      },
    };
  }
  if (gn.type === 'style') {
    return { id: gn.id, type: 'style', position: gn.position, data: { styleId: gn.data.styleId as string, onLoaded: cb.onStyleLoaded, onUpdate: cb.onStyleUpdate } };
  }
  return null;
}

function toGraphNode(n: Node): GraphNode {
  if (n.type === 'scratch-image') {
    const d = n.data as ScratchImageNodeData;
    return { id: n.id, type: 'scratch-image', position: n.position, data: { prompt: d.prompt, url: d.url, localPath: d.localPath } };
  }
  if (n.type === 'scratch-music') {
    const d = n.data as ScratchMusicNodeData;
    return { id: n.id, type: 'scratch-music', position: n.position, data: { prompt: d.prompt, negativePrompt: d.negativePrompt, url: d.url } };
  }
  if (n.type === 'style') {
    const d = n.data as StyleNodeData;
    return { id: n.id, type: 'style', position: n.position, data: { styleId: d.styleId } };
  }
  throw new Error(`unknown scratch node type: ${n.type}`);
}

// Style is the one node type genuinely shared with the city pipeline (it
// belongs to the global library, not any board) -- same merge logic as
// pipeline.ts's Frame/Video enrichment, just scoped to the one consumer
// scratch boards have (scratch-image's style:in).
function enrichScratchNodes(nodes: Node[], edges: Edge[]): Node[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  return nodes.map((n) => {
    if (n.type !== 'scratch-image') return n;
    const styles = edges
      .filter((e) => e.target === n.id && e.targetHandle === 'style:in')
      .map((e) => byId.get(e.source))
      .filter((s): s is Node => Boolean(s && s.type === 'style'))
      .map((s) => (s.data as StyleNodeData).style)
      .filter((s): s is Style => Boolean(s));
    if (styles.length === 0) return n;
    return {
      ...n,
      data: {
        ...n.data,
        mergedStylePrompt: styles.map((s) => s.style_prompt).filter(Boolean).join(', ') || undefined,
        mergedStyleReferenceImages: styles.flatMap((s) => s.reference_images),
      },
    };
  });
}

function ScratchCanvasInner({ boardId }: { boardId: string }) {
  const { doc, save } = usePersistedGraph(`scratch:${boardId}`);
  const [nodes, setNodes] = useState<Node[] | null>(null);
  const [edges, setEdges] = useState<Edge[]>([]);
  const initializedFor = useRef<string | null>(null);

  const onImageUpdate = useCallback((nodeId: string, patch: Partial<ScratchImageNodeData>) => {
    setNodes((prev) => (prev ? prev.map((n) => (n.id === nodeId ? { ...n, data: { ...n.data, ...patch } } : n)) : prev));
  }, []);
  const onMusicUpdate = useCallback((nodeId: string, patch: Partial<ScratchMusicNodeData>) => {
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

  // No reconciliation here, deliberately -- unlike CityCanvas/EntityCanvas
  // nodes (which reference char_*/place_*/media_* ids that can go stale),
  // a scratch node's own data (prompt, url, localPath) IS its entire
  // state; there's no external entity it could drift out of sync with.
  useEffect(() => {
    if (!doc) return;
    const key = `${doc.rev}`;
    if (initializedFor.current === key && nodes) return;
    initializedFor.current = key;
    const cb = { onImageUpdate, onMusicUpdate, onStyleLoaded, onStyleUpdate };
    setNodes(doc.nodes.map((gn) => toRenderNode(gn, cb)).filter((n): n is Node => n !== null));
    setEdges(doc.edges.map(toFlowEdge));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

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

  const addNode = useCallback(
    (type: 'scratch-image' | 'scratch-music') => {
      setNodes((prev) => {
        const list = prev ?? [];
        const position = gridPosition(list.length, { columns: 4, cellWidth: 280, cellHeight: 240 });
        const id = newNodeId(type);
        if (type === 'scratch-image') return [...list, { id, type, position, data: { prompt: '', onUpdate: onImageUpdate } }];
        return [...list, { id, type, position, data: { prompt: '', negativePrompt: '', onUpdate: onMusicUpdate } }];
      });
    },
    [onImageUpdate, onMusicUpdate],
  );

  const addStyleNode = useCallback(async () => {
    let created;
    try {
      created = await stylesApi.create({ name: 'New Style', stylePrompt: '' });
    } catch (e) {
      console.error('failed to create style', e);
      return;
    }
    setNodes((prev) => {
      const list = prev ?? [];
      const position = gridPosition(list.length, { columns: 4, cellWidth: 280, cellHeight: 240 });
      return [...list, { id: newNodeId('style'), type: 'style', position, data: { styleId: created.style.id, style: created.style, onLoaded: onStyleLoaded, onUpdate: onStyleUpdate } }];
    });
  }, [onStyleLoaded, onStyleUpdate]);

  if (!nodes) return <div className="canvas-empty">Loading canvas…</div>;

  return (
    <div className="city-canvas-layout">
      <div className="canvas-with-tray">
        <ReactFlow
          nodes={enrichScratchNodes(nodes, edges)}
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
          <Panel position="top-right" className="canvas-toolbar">
            <button className="node-run-btn" onClick={() => addNode('scratch-image')}>
              + Image
            </button>
            <button className="node-run-btn" onClick={() => addNode('scratch-music')}>
              + Music
            </button>
            <button className="node-run-btn" onClick={addStyleNode}>
              + Style
            </button>
          </Panel>
        </ReactFlow>
      </div>
    </div>
  );
}

export function ScratchScreen({ boardId }: { boardId: string }) {
  return (
    <ReactFlowProvider>
      <ScratchCanvasInner boardId={boardId} />
    </ReactFlowProvider>
  );
}
