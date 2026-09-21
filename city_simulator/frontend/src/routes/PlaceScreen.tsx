import { useCallback, useEffect, useState } from 'react';
import { history } from '../api/client';
import type { HistoryData } from '../api/types';
import { EntityCanvas } from '../flow/EntityCanvas';
import { CollapsibleAside } from '../inspector/CollapsibleAside';
import { PlaceDetail } from '../inspector/PlaceDetail';
import '../inspector/inspector.css';

export function PlaceScreen({ cityId, placeId }: { cityId: string; placeId: string }) {
  const [data, setData] = useState<HistoryData | null | undefined>(undefined);

  // GET /api/history/data reads the *active* city implicitly -- arriving
  // here directly (a bookmark, a refresh) can't assume cityId is already
  // active, so it's activated first, same as CityCanvas. This also
  // doubles as the "refresh city data" callback EntityCanvas needs after
  // creating a new agent node -- it's already the full HistoryData this
  // screen itself uses for PlaceDetail, so no separate loading state.
  const load = useCallback(() => {
    history
      .activateCity(cityId)
      .then((res) => setData(res.city))
      .catch(() => setData(null));
  }, [cityId]);

  useEffect(load, [load]);

  if (data === undefined) return <div className="canvas-empty">Loading…</div>;
  if (data === null) return <div className="canvas-empty">No such city.</div>;

  return (
    <div className="city-canvas-layout">
      <EntityCanvas cityId={cityId} entityId={placeId} scope={`place:${placeId}`} media={data.media[placeId] ?? []} cityData={data} onCityDataRefresh={load} />
      <CollapsibleAside>
        <PlaceDetail placeId={placeId} data={data} />
      </CollapsibleAside>
    </div>
  );
}
