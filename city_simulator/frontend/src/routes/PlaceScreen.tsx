import { useEffect, useState } from 'react';
import { history } from '../api/client';
import type { HistoryData } from '../api/types';
import { EntityCanvas } from '../flow/EntityCanvas';
import { PlaceDetail } from '../inspector/PlaceDetail';
import '../inspector/inspector.css';

export function PlaceScreen({ cityId, placeId }: { cityId: string; placeId: string }) {
  const [data, setData] = useState<HistoryData | null | undefined>(undefined);

  useEffect(() => {
    setData(undefined);
    // GET /api/history/data reads the *active* city implicitly --
    // arriving here directly (a bookmark, a refresh) can't assume cityId
    // is already active, so it's activated first, same as CityCanvas.
    history
      .activateCity(cityId)
      .then((res) => setData(res.city))
      .catch(() => setData(null));
  }, [cityId]);

  if (data === undefined) return <div className="canvas-empty">Loading…</div>;
  if (data === null) return <div className="canvas-empty">No such city.</div>;

  return (
    <div className="city-canvas-layout">
      <EntityCanvas entityId={placeId} scope={`place:${placeId}`} media={data.media[placeId] ?? []} />
      <aside className="inspector">
        <PlaceDetail placeId={placeId} data={data} />
      </aside>
    </div>
  );
}
