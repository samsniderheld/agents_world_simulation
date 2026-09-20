import type { Selection } from '../flow/selection';
import type { HistoryData } from '../api/types';
import { AgentDetail } from './AgentDetail';
import { CityOverview } from './CityOverview';
import './inspector.css';
import { PlaceDetail } from './PlaceDetail';

export function Inspector({ selection, data }: { selection: Selection; data: HistoryData }) {
  return (
    <aside className="inspector">
      {selection.kind === 'city' && <CityOverview data={data} />}
      {selection.kind === 'agent' && <AgentDetail characterId={selection.characterId} />}
      {selection.kind === 'place' && <PlaceDetail placeId={selection.placeId} data={data} />}
    </aside>
  );
}
