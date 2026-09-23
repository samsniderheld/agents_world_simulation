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
  // `from` defaults to this agent's own city (unchanged, existing
  // behavior) when absent -- set only when arriving via the Gallery, so
  // Esc/the breadcrumb goes back there instead, same mechanism as
  // scratch/storyboard's own `from` below.
  | { kind: 'agent'; cityId: string; agentId: string; from?: Scope }
  | { kind: 'place'; cityId: string; placeId: string; from?: Scope }
  // A city-scoped card view of its Agents/Locations (routes/
  // GalleryScreen.tsx) -- always nests under its own city in the
  // breadcrumb, so unlike scratch/storyboard it never needs its own
  // `from`.
  | { kind: 'gallery'; cityId: string }
  // `from` is wherever the header's "Scratch" button was clicked from --
  // a Scratch board is a single fixed global board reachable from any
  // screen, not owned by a city the way Agent/Place are, so without this
  // there'd be no "one level up" back to whatever city/agent/place the
  // user actually came from. Same mechanism as Storyboard's own `from`
  // below (carried in the URL's `?from=` param so a bookmark/refresh
  // preserves it).
  | { kind: 'scratch'; boardId: string; from?: Scope }
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
  if (agent) {
    const rawFrom = new URLSearchParams(search).get('from');
    return {
      kind: 'agent',
      cityId: decodeURIComponent(agent[1]),
      agentId: decodeURIComponent(agent[2]),
      from: rawFrom ? parseFrom(decodeURIComponent(rawFrom)) : undefined,
    };
  }

  const place = pathname.match(/^\/c\/([^/]+)\/place\/([^/]+)\/?$/);
  if (place) {
    const rawFrom = new URLSearchParams(search).get('from');
    return {
      kind: 'place',
      cityId: decodeURIComponent(place[1]),
      placeId: decodeURIComponent(place[2]),
      from: rawFrom ? parseFrom(decodeURIComponent(rawFrom)) : undefined,
    };
  }

  const gallery = pathname.match(/^\/c\/([^/]+)\/gallery\/?$/);
  if (gallery) return { kind: 'gallery', cityId: decodeURIComponent(gallery[1]) };

  const city = pathname.match(/^\/c\/([^/]+)\/?$/);
  if (city) return { kind: 'city', cityId: decodeURIComponent(city[1]) };

  const scratch = pathname.match(/^\/scratch\/([^/]+)\/?$/);
  if (scratch) {
    const rawFrom = new URLSearchParams(search).get('from');
    return {
      kind: 'scratch',
      boardId: decodeURIComponent(scratch[1]),
      from: rawFrom ? parseFrom(decodeURIComponent(rawFrom)) : undefined,
    };
  }

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
    case 'agent': {
      const base = `/c/${encodeURIComponent(scope.cityId)}/agent/${encodeURIComponent(scope.agentId)}`;
      return scope.from ? `${base}?from=${encodeURIComponent(pathFor(scope.from))}` : base;
    }
    case 'place': {
      const base = `/c/${encodeURIComponent(scope.cityId)}/place/${encodeURIComponent(scope.placeId)}`;
      return scope.from ? `${base}?from=${encodeURIComponent(pathFor(scope.from))}` : base;
    }
    case 'gallery':
      return `/c/${encodeURIComponent(scope.cityId)}/gallery`;
    case 'scratch': {
      const base = `/scratch/${encodeURIComponent(scope.boardId)}`;
      return scope.from ? `${base}?from=${encodeURIComponent(pathFor(scope.from))}` : base;
    }
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
