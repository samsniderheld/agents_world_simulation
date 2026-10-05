import { useCallback, useEffect, useState } from 'react';
import { city, history } from '../api/client';
import type { AgentRecord, HistoryData } from '../api/types';
import { CharacterView } from '../inspector/CharacterView';
import { CollapsibleAside } from '../inspector/CollapsibleAside';
import '../inspector/inspector.css';
import { EntityCanvas } from '../flow/EntityCanvas';
import type { Scope } from './router';

// A hero's page. The character view (sheet first, then story, memories,
// people, plans, media...) is the primary view -- the same one a
// background resident's page shows; their node canvas (images, video,
// storyboards for them) is one switch away, with the character view in
// its side panel.
export function AgentScreen({ cityId, characterId, from }: { cityId: string; characterId: string; from?: Scope }) {
  const [view, setView] = useState<'character' | 'canvas'>('character');
  const here: Scope = { kind: 'agent', cityId, agentId: characterId, from };

  useEffect(() => setView('character'), [characterId]);

  if (view === 'character') {
    return (
      <CharacterView
        personId={characterId}
        cityId={cityId}
        layout="page"
        activate
        from={here}
        headerExtra={
          <button className="node-run-btn" onClick={() => setView('canvas')} title="Their node canvas: images, video, storyboards">
            canvas →
          </button>
        }
      />
    );
  }
  return <AgentCanvas cityId={cityId} characterId={characterId} from={here} onBack={() => setView('character')} />;
}

function AgentCanvas({ cityId, characterId, from, onBack }: { cityId: string; characterId: string; from: Scope; onBack: () => void }) {
  const [record, setRecord] = useState<AgentRecord | null | undefined>(undefined);
  const [cityData, setCityData] = useState<HistoryData | null>(null);

  // GET /api/city/agents/<id> reads the *active* city implicitly, so the
  // city is activated first; its response is the full city EntityCanvas
  // needs for its Agents/Locations sections.
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
  // from within this canvas) without flashing the screen back to Loading.
  const refreshCityData = useCallback(() => {
    history.activateCity(cityId).then((res) => setCityData(res.city)).catch(() => {});
  }, [cityId]);

  // The side panel keeps its own copy of this agent; deleting media there
  // has to refresh the canvas's `media` too.
  const refreshRecord = useCallback(() => {
    city.getAgent(characterId).then(setRecord).catch(() => {});
  }, [characterId]);

  if (record === undefined) return <div className="canvas-empty">Loading…</div>;
  if (record === null) return <div className="canvas-empty">No such agent.</div>;

  return (
    <div className="city-canvas-layout">
      <div className="agent-canvas-wrap">
        <button className="node-run-btn agent-canvas-back" onClick={onBack}>
          ← character
        </button>
        <EntityCanvas cityId={cityId} entityId={characterId} scope={`agent:${characterId}`} media={record.media} cityData={cityData} onCityDataRefresh={refreshCityData} />
      </div>
      <CollapsibleAside>
        <CharacterView personId={characterId} cityId={cityId} layout="drawer" from={from} onMediaChanged={refreshRecord} />
      </CollapsibleAside>
    </div>
  );
}
