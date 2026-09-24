// Save the current canvas into the global "Saved graphs" library, and load
// one back later -- added alongside what's already on the canvas, or
// replacing it. Works entirely on server copies (flush autosave first, then
// read /api/graph/<scope>), so it's the same for every canvas type and never
// needs to know how a canvas turns its React Flow nodes into graph nodes.
//
// Storyboards: a Storyboard node's id IS the scope of its inner canvas, so
// saving captures every Storyboard's inner canvas too (recursively), and
// loading gives each copy a fresh scope with its inner canvas re-created --
// otherwise a loaded Storyboard would be an empty shell, or worse, share
// (and overwrite) the original's inner canvas.
import { useCallback, useEffect, useState } from 'react';
import { graph, graphLibrary } from '../api/client';
import type { GraphBody, GraphDoc, GraphEdge, GraphNode, SavedGraphSummary } from '../api/types';
import { newNodeId } from './graphIds';

// These ids point at real residents/places (agent:<char_id>, place:<id>),
// so they keep them: the same Agent on two canvases is the same Agent.
const ENTITY_TYPES = new Set(['agent', 'location', 'missing']);

export type LoadMode = 'add' | 'replace';

async function collectStoryboards(root: GraphBody): Promise<Record<string, GraphBody>> {
  const out: Record<string, GraphBody> = {};
  const queue = root.nodes.filter((n) => n.type === 'storyboard').map((n) => n.id);
  while (queue.length) {
    const scope = queue.shift()!;
    if (out[scope]) continue;
    const doc = await graph.get(scope);
    out[scope] = { nodes: doc.nodes, edges: doc.edges };
    for (const n of doc.nodes) if (n.type === 'storyboard' && !out[n.id]) queue.push(n.id);
  }
  return out;
}

function remap(body: GraphBody, ids: Map<string, string>): GraphBody {
  const nodes = body.nodes.map((n) => ({ ...n, id: ids.get(n.id) ?? n.id }));
  const edges = body.edges.map((e): GraphEdge => {
    const source = ids.get(e.source) ?? e.source;
    const target = ids.get(e.target) ?? e.target;
    return { ...e, id: `e:${source}:${e.sourceHandle}->${target}:${e.targetHandle}`, source, target };
  });
  return { nodes, edges };
}

function bounds(nodes: GraphNode[]) {
  const xs = nodes.map((n) => n.position.x), ys = nodes.map((n) => n.position.y);
  return {
    minX: Math.min(...xs), minY: Math.min(...ys),
    maxX: Math.max(...nodes.map((n) => n.position.x + (n.width ?? 320))),
  };
}

export function useGraphLibrary(
  scope: string,
  persisted: { flush: () => Promise<void>; adopt: (doc: GraphDoc) => void },
) {
  const [saved, setSaved] = useState<SavedGraphSummary[]>([]);
  const refresh = useCallback(() => {
    graphLibrary.list().then((r) => setSaved(r.graphs)).catch(() => setSaved([]));
  }, []);
  useEffect(refresh, [refresh]);

  const { flush, adopt } = persisted;

  const saveCurrent = useCallback(
    async (name: string) => {
      await flush();
      const doc = await graph.get(scope);
      const root = { nodes: doc.nodes, edges: doc.edges };
      await graphLibrary.save({ name, root, storyboards: await collectStoryboards(root), sourceScope: scope });
      refresh();
    },
    [scope, flush, refresh],
  );

  const load = useCallback(
    async (graphId: string, mode: LoadMode) => {
      const { graph: bundle } = await graphLibrary.get(graphId);

      // One id map across the root and every inner canvas, so a Storyboard
      // nested inside a Storyboard still lines up with its own copied scope.
      const ids = new Map<string, string>();
      for (const body of [bundle.root, ...Object.values(bundle.storyboards)]) {
        for (const n of body.nodes) {
          if (!ENTITY_TYPES.has(n.type) && !ids.has(n.id)) ids.set(n.id, newNodeId(n.type));
        }
      }

      // Recreate each Storyboard's inner canvas under its new scope first,
      // so it's already there by the time anyone opens the copy.
      await Promise.all(
        Object.entries(bundle.storyboards).map(([oldScope, body]) => {
          const newScope = ids.get(oldScope);
          if (!newScope) return Promise.resolve();
          return graph.put(newScope, { version: 1, rev: 0, viewport: { x: 0, y: 0, zoom: 1 }, ...remap(body, ids) });
        }),
      );

      await flush();
      const current = await graph.get(scope);
      const incoming = remap(bundle.root, ids);
      let nodes: GraphNode[], edges: GraphEdge[];
      if (mode === 'replace' || current.nodes.length === 0) {
        nodes = incoming.nodes;
        edges = incoming.edges;
      } else {
        // Add to the right of what's there, top-aligned; an Agent/Location
        // already on this canvas isn't duplicated -- the loaded edges just
        // attach to the existing one.
        const have = new Set(current.nodes.map((n) => n.id));
        const fresh = incoming.nodes.filter((n) => !have.has(n.id));
        if (fresh.length) {
          const cur = bounds(current.nodes), inc = bounds(fresh);
          const dx = cur.maxX + 200 - inc.minX, dy = cur.minY - inc.minY;
          fresh.forEach((n) => (n.position = { x: n.position.x + dx, y: n.position.y + dy }));
        }
        const haveEdges = new Set(current.edges.map((e) => e.id));
        nodes = [...current.nodes, ...fresh];
        edges = [...current.edges, ...incoming.edges.filter((e) => !haveEdges.has(e.id))];
      }
      const written = await graph.put(scope, { version: current.version, rev: current.rev, viewport: current.viewport, nodes, edges });
      adopt(written);
    },
    [scope, flush, adopt],
  );

  const remove = useCallback(
    async (graphId: string) => {
      await graphLibrary.remove(graphId);
      refresh();
    },
    [refresh],
  );

  return { saved, saveCurrent, load, remove };
}
