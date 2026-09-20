// A small hand-rolled scope router -- each scope is a real URL with its
// own independently-loaded canvas (per the design spec's Part I.3: real
// routes, not React Flow parent/child subflows). Deliberately no router
// library: six route shapes with no nesting/data-loading concerns don't
// need one.
//
// Agent/Location scopes carry their city's id even though char_*/place_*
// ids are already globally unique -- not for lookup (GET /api/city/
// agents/<id> only ever reads the *active* city regardless), but because
// two real things need it: the breadcrumb's "back" link has to know
// which city to return to, and arriving here directly (a bookmark, a
// refresh) has to activate the right city first or it'd silently read
// whichever city happened to already be active. Scratch boards stay
// global -- they don't belong to any city at all.
import { useEffect, useState } from 'react';

export type Scope =
  | { kind: 'root' }
  | { kind: 'city'; cityId: string }
  | { kind: 'agent'; cityId: string; agentId: string }
  | { kind: 'place'; cityId: string; placeId: string }
  | { kind: 'scratch'; boardId: string };

function parse(pathname: string): Scope {
  const agent = pathname.match(/^\/c\/([^/]+)\/agent\/([^/]+)\/?$/);
  if (agent) return { kind: 'agent', cityId: decodeURIComponent(agent[1]), agentId: decodeURIComponent(agent[2]) };

  const place = pathname.match(/^\/c\/([^/]+)\/place\/([^/]+)\/?$/);
  if (place) return { kind: 'place', cityId: decodeURIComponent(place[1]), placeId: decodeURIComponent(place[2]) };

  const city = pathname.match(/^\/c\/([^/]+)\/?$/);
  if (city) return { kind: 'city', cityId: decodeURIComponent(city[1]) };

  const scratch = pathname.match(/^\/scratch\/([^/]+)\/?$/);
  if (scratch) return { kind: 'scratch', boardId: decodeURIComponent(scratch[1]) };

  return { kind: 'root' };
}

export function pathFor(scope: Scope): string {
  switch (scope.kind) {
    case 'root':
      return '/';
    case 'city':
      return `/c/${encodeURIComponent(scope.cityId)}`;
    case 'agent':
      return `/c/${encodeURIComponent(scope.cityId)}/agent/${encodeURIComponent(scope.agentId)}`;
    case 'place':
      return `/c/${encodeURIComponent(scope.cityId)}/place/${encodeURIComponent(scope.placeId)}`;
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
