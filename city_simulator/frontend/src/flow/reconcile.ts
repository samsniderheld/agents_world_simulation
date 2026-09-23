// Node data holds entity references, never copies (a char_*/place_* id),
// so a persisted graph can drift from the live city: an entity generated
// since the canvas was last saved has no node yet, and a node can
// reference an entity that no longer exists (city regenerated with fresh
// ids). Per the design spec: the former goes in a "not on canvas" tray,
// the latter renders as a dimmed "missing" node with a Remove action --
// never silently dropped or auto-added, since both are the user's own
// arrangement to keep or discard.
import type { GraphNode } from '../api/types';

export interface Reconciled {
  present: GraphNode[];
  missing: GraphNode[];
  notOnCanvas: string[];
}

export function reconcile(nodes: GraphNode[], entityIds: string[], entityIdOf: (n: GraphNode) => string | undefined): Reconciled {
  const idSet = new Set(entityIds);
  const present: GraphNode[] = [];
  const missing: GraphNode[] = [];
  const seen = new Set<string>();

  for (const n of nodes) {
    const id = entityIdOf(n);
    if (id && idSet.has(id)) {
      present.push(n);
      seen.add(id);
    } else {
      missing.push(n);
    }
  }

  return { present, missing, notOnCanvas: entityIds.filter((id) => !seen.has(id)) };
}
