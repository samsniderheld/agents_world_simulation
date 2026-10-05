import type { Selection } from '../flow/selection';
import type { HistoryData } from '../api/types';
import { CharacterView } from './CharacterView';
import { CityOverview } from './CityOverview';
import { CollapsibleAside } from './CollapsibleAside';
import './inspector.css';
import { PlaceDetail } from './PlaceDetail';

export function Inspector({ cityId, selection, data, onDataRefresh }: { cityId: string; selection: Selection; data: HistoryData; onDataRefresh?: () => void }) {
  return (
    <CollapsibleAside>
      {selection.kind === 'city' && <CityOverview data={data} />}
      {selection.kind === 'agent' && (
        <CharacterView personId={selection.characterId} cityId={cityId} layout="drawer" onMediaChanged={onDataRefresh} />
      )}
      {selection.kind === 'place' && <PlaceDetail placeId={selection.placeId} data={data} onRefresh={onDataRefresh} />}
    </CollapsibleAside>
  );
}
