// A small hand-rolled scope router -- each scope is a real URL with its
// own independently-loaded canvas (per the design spec's Part I.3: real
// routes, not React Flow parent/child subflows), but there's no city
// *collection* yet (that's Phase 5 -- see citystate/store.py, still a
// single active-city record), so there's no /c/:cityId segment yet
// either. Phase 5 adds a real city id here; until then "the active city"
// is implicit, matching the backend. Deliberately no router library:
// five route shapes with no nesting/data-loading concerns don't need one.
import { useEffect, useState } from 'react';

export type Scope =
  | { kind: 'city' }
  | { kind: 'agent'; agentId: string }
  | { kind: 'place'; placeId: string }
  | { kind: 'scratch'; boardId: string };

function parse(pathname: string): Scope {
  const agent = pathname.match(/^\/agent\/([^/]+)\/?$/);
  if (agent) return { kind: 'agent', agentId: decodeURIComponent(agent[1]) };

  const place = pathname.match(/^\/place\/([^/]+)\/?$/);
  if (place) return { kind: 'place', placeId: decodeURIComponent(place[1]) };

  const scratch = pathname.match(/^\/scratch\/([^/]+)\/?$/);
  if (scratch) return { kind: 'scratch', boardId: decodeURIComponent(scratch[1]) };

  return { kind: 'city' };
}

export function pathFor(scope: Scope): string {
  switch (scope.kind) {
    case 'city':
      return '/';
    case 'agent':
      return `/agent/${encodeURIComponent(scope.agentId)}`;
    case 'place':
      return `/place/${encodeURIComponent(scope.placeId)}`;
    case 'scratch':
      return `/scratch/${encodeURIComponent(scope.boardId)}`;
  }
}

export function navigate(scope: Scope) {
  const path = pathFor(scope);
  if (path !== window.location.pathname) {
    window.history.pushState(null, '', path);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }
}

export function useRoute(): Scope {
  const [scope, setScope] = useState<Scope>(() => parse(window.location.pathname));

  useEffect(() => {
    const onPopState = () => setScope(parse(window.location.pathname));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  return scope;
}
