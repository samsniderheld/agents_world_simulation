import { CharacterView } from '../inspector/CharacterView';
import { navigate } from './router';
import type { Scope } from './router';

// A CITY background resident's page: the same character view as a hero's
// (inspector/CharacterView.tsx). A resident who has been made a hero is
// that hero, so their page redirects to the hero's.
export function ResidentScreen({ cityId, residentId, from }: { cityId: string; residentId: string; from?: Scope }) {
  return (
    <CharacterView
      personId={residentId}
      cityId={cityId}
      layout="page"
      activate
      from={{ kind: 'resident', cityId, residentId, from }}
      onLoaded={(p) => {
        if (p.kind === 'hero') navigate({ kind: 'agent', cityId, agentId: p.id, from }, { replace: true });
      }}
    />
  );
}
