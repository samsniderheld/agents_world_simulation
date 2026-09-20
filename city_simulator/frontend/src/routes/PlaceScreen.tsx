import { useEffect, useState } from 'react';
import { history } from '../api/client';
import type { HistoryData } from '../api/types';
import { EntityCanvas } from '../flow/EntityCanvas';
import { PlaceDetail } from '../inspector/PlaceDetail';
import '../inspector/inspector.css';

export function PlaceScreen({ placeId }: { placeId: string }) {
  const [data, setData] = useState<HistoryData | null | undefined>(undefined);

  useEffect(() => {
    history
      .data()
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (data === undefined) return <div className="canvas-empty">Loading…</div>;
  if (data === null) return <div className="canvas-empty">No active city.</div>;

  return (
    <div className="city-canvas-layout">
      <EntityCanvas entityId={placeId} scope={`place:${placeId}`} media={data.media[placeId] ?? []} />
      <aside className="inspector">
        <PlaceDetail placeId={placeId} data={data} />
      </aside>
    </div>
  );
}
