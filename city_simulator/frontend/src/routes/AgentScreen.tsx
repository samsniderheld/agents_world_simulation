import { useCallback, useEffect, useState } from 'react';
import { city, history } from '../api/client';
import type { AgentRecord, HistoryData } from '../api/types';
import { AgentDetail } from '../inspector/AgentDetail';
import { CollapsibleAside } from '../inspector/CollapsibleAside';
import '../inspector/inspector.css';
import { EntityCanvas } from '../flow/EntityCanvas';

export function AgentScreen({ cityId, characterId }: { cityId: string; characterId: string }) {
  const [record, setRecord] = useState<AgentRecord | null | undefined>(undefined);
  const [cityData, setCityData] = useState<HistoryData | null>(null);

  // GET /api/city/agents/<id> reads the *active* city implicitly --
  // arriving here directly (a bookmark, a refresh) can't assume cityId
  // is already active, so it's activated first, same as CityCanvas. The
  // activation response already hands back the full city (HistoryData),
  // which EntityCanvas needs for its Agents/Locations sections -- no
  // second fetch required.
  const load = useCallback(() => {
    setRecord(undefined);
    history
      .activateCity(cityId)
      .then((res) => {
        setCityData(res.city);
        return city.getAgent(characterId);
      })
      .then(setRecord)
      .catch(() => setRecord(null));
  }, [cityId, characterId]);

  useEffect(load, [load]);

  // Refreshes just the city data (e.g. after creating a new agent node
  // from within this screen's own canvas) without flashing the whole
  // screen back to "Loading…" the way `load` above would.
  const refreshCityData = useCallback(() => {
    history.activateCity(cityId).then((res) => setCityData(res.city)).catch(() => {});
  }, [cityId]);

  if (record === undefined) return <div className="canvas-empty">Loading…</div>;
  if (record === null) return <div className="canvas-empty">No such agent.</div>;

  return (
    <div className="city-canvas-layout">
      <EntityCanvas cityId={cityId} entityId={characterId} scope={`agent:${characterId}`} media={record.media} cityData={cityData} onCityDataRefresh={refreshCityData} />
      <CollapsibleAside>
        <AgentDetail characterId={characterId} />
      </CollapsibleAside>
    </div>
  );
}
