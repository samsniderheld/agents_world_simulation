import { useEffect, useState } from 'react';
import { city } from '../api/client';
import type { AgentRecord } from '../api/types';
import { AgentDetail } from '../inspector/AgentDetail';
import '../inspector/inspector.css';
import { EntityCanvas } from '../flow/EntityCanvas';

export function AgentScreen({ characterId }: { characterId: string }) {
  const [record, setRecord] = useState<AgentRecord | null | undefined>(undefined);

  useEffect(() => {
    setRecord(undefined);
    city
      .getAgent(characterId)
      .then(setRecord)
      .catch(() => setRecord(null));
  }, [characterId]);

  if (record === undefined) return <div className="canvas-empty">Loading…</div>;
  if (record === null) return <div className="canvas-empty">No such agent.</div>;

  return (
    <div className="city-canvas-layout">
      <EntityCanvas entityId={characterId} scope={`agent:${characterId}`} media={record.media} />
      <aside className="inspector">
        <AgentDetail characterId={characterId} />
      </aside>
    </div>
  );
}
