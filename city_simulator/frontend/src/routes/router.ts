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
  | { kind: 'scratch'; boardId: string }
  // `from` is which canvas this Storyboard was opened from (City, Agent,
  // Place, Scratch, or another Storyboard) -- unlike every other scope,
  // Storyboard doesn't inherently belong anywhere, so without this
  // there'd be no "one level up" to go to: Esc/the breadcrumb would have
  // to jump straight to the root Cities list instead of back to wherever
  // the user actually drilled in from. Carried in the URL's `?from=`
  // param (see pathFor/parse below) so a bookmark or refresh preserves it.
  | { kind: 'storyboard'; storyboardId: string; from?: Scope };

function parseFrom(raw: string): Scope | undefined {
  const qIdx = raw.indexOf('?');
  const pathname = qIdx === -1 ? raw : raw.slice(0, qIdx);
  const search = qIdx === -1 ? '' : raw.slice(qIdx);
  return parse(pathname, search);
}

function parse(pathname: string, search: string): Scope {
  const agent = pathname.match(/^\/c\/([^/]+)\/agent\/([^/]+)\/?$/);
  if (agent) return { kind: 'agent', cityId: decodeURIComponent(agent[1]), agentId: decodeURIComponent(agent[2]) };

  const place = pathname.match(/^\/c\/([^/]+)\/place\/([^/]+)\/?$/);
  if (place) return { kind: 'place', cityId: decodeURIComponent(place[1]), placeId: decodeURIComponent(place[2]) };

  const city = pathname.match(/^\/c\/([^/]+)\/?$/);
  if (city) return { kind: 'city', cityId: decodeURIComponent(city[1]) };

  const scratch = pathname.match(/^\/scratch\/([^/]+)\/?$/);
  if (scratch) return { kind: 'scratch', boardId: decodeURIComponent(scratch[1]) };

  // No cityId segment -- a Storyboard can be created from a City, Agent,
  // Place, or Scratch canvas alike and doesn't "belong" to one, same
  // reasoning as scratch boards above.
  const storyboard = pathname.match(/^\/storyboard\/([^/]+)\/?$/);
  if (storyboard) {
    const rawFrom = new URLSearchParams(search).get('from');
    return {
      kind: 'storyboard',
      storyboardId: decodeURIComponent(storyboard[1]),
      from: rawFrom ? parseFrom(decodeURIComponent(rawFrom)) : undefined,
    };
  }

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
    case 'storyboard': {
      const base = `/storyboard/${encodeURIComponent(scope.storyboardId)}`;
      return scope.from ? `${base}?from=${encodeURIComponent(pathFor(scope.from))}` : base;
    }
  }
}

export function navigate(scope: Scope) {
  const path = pathFor(scope);
  if (path !== window.location.pathname + window.location.search) {
    window.history.pushState(null, '', path);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }
}

export function useRoute(): Scope {
  const [scope, setScope] = useState<Scope>(() => parse(window.location.pathname, window.location.search));

  useEffect(() => {
    const onPopState = () => setScope(parse(window.location.pathname, window.location.search));
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  return scope;
}
