import type { Selection } from '../flow/selection';
import type { HistoryData } from '../api/types';
import { AgentDetail } from './AgentDetail';
import { CityOverview } from './CityOverview';
import { CollapsibleAside } from './CollapsibleAside';
import './inspector.css';
import { PlaceDetail } from './PlaceDetail';

export function Inspector({ selection, data, onDataRefresh }: { selection: Selection; data: HistoryData; onDataRefresh?: () => void }) {
  return (
    <CollapsibleAside>
      {selection.kind === 'city' && <CityOverview data={data} />}
      {selection.kind === 'agent' && <AgentDetail characterId={selection.characterId} onMediaChanged={onDataRefresh} />}
      {selection.kind === 'place' && <PlaceDetail placeId={selection.placeId} data={data} onRefresh={onDataRefresh} />}
    </CollapsibleAside>
  );
}
