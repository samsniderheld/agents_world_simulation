// Loads and autosaves one scope's graph document (GET/PUT /api/graph/
// <scope>). Debounced 600ms after the last change and flushed on unmount
// (a route change unmounts the previous scope's canvas) -- matches the
// design spec's Part I.4. Viewport isn't tracked yet (nodes/edges are the
// load-bearing part); it's just round-tripped as last-loaded.
//
// Conflict handling is deliberately minimal: this is a single local user,
// so a 409 almost certainly means a second browser tab open on the same
// scope, not real concurrent editing to merge -- the design spec itself
// argues a rev conflict "should never fire in practice" here. On one,
// this just adopts the server's version rather than building merge UI.
import { useCallback, useEffect, useRef, useState } from 'react';
import { graph, GraphRevConflict } from '../api/client';
import type { GraphDoc, GraphEdge, GraphNode } from '../api/types';

const AUTOSAVE_DEBOUNCE_MS = 600;

export function usePersistedGraph(scope: string) {
  const [doc, setDoc] = useState<GraphDoc | null>(null);
  const docRef = useRef<GraphDoc | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingRef = useRef<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);

  // Returns the save's promise (resolved immediately when nothing's
  // pending), so a caller that needs the server copy current -- saving the
  // canvas into the library -- can wait for it.
  const flush = useCallback((): Promise<void> => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    const pending = pendingRef.current;
    const current = docRef.current;
    if (!pending || !current) return Promise.resolve();
    pendingRef.current = null;

    return graph
      .put(scope, {
        version: current.version,
        rev: current.rev,
        viewport: current.viewport,
        nodes: pending.nodes,
        edges: pending.edges,
      })
      .then((saved) => {
        // Only rev/version/viewport (for the *next* save's optimistic-
        // concurrency check) go back into docRef -- NOT into the `doc`
        // React state. The caller's own local nodes/edges are already
        // exactly what was just saved; re-exposing it here would trigger
        // a re-render that resets whatever the caller's derived from
        // `doc.nodes` on mount, fighting its own in-progress edits.
        docRef.current = saved;
      })
      .catch((e) => {
        if (e instanceof GraphRevConflict) {
          docRef.current = e.current;
          setDoc(e.current);
        }
      });
  }, [scope]);

  useEffect(() => {
    let cancelled = false;
    setDoc(null);
    docRef.current = null;
    graph.get(scope).then((d) => {
      if (cancelled) return;
      docRef.current = d;
      setDoc(d);
    });
    return () => {
      cancelled = true;
      flush();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope]);

  const save = useCallback(
    (nodes: GraphNode[], edges: GraphEdge[]) => {
      pendingRef.current = { nodes, edges };
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(flush, AUTOSAVE_DEBOUNCE_MS);
    },
    [flush],
  );

  // Swap in a document just written to this scope by something other than
  // autosave (loading a saved graph) -- the caller's rebuild effect sees a
  // new `doc.rev` and rebuilds from it, exactly like a fresh load.
  const adopt = useCallback((next: GraphDoc) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = null;
    pendingRef.current = null;
    docRef.current = next;
    setDoc(next);
  }, []);

  return { doc, save, flush, adopt };
}
