import { useState } from 'react';
import type { HistoryData } from '../api/types';
import { MediaGrid } from './MediaGrid';

type Tab = 'architecture' | 'history' | 'ownership' | 'media';

// Unlike AgentDetail, this component owns no fetch of its own -- `data`
// is entirely the caller's -- so deleting media has nothing local to
// update; `onRefresh` (the caller's own HistoryData refetch) is the only
// way this ever sees the media list change.
export function PlaceDetail({ placeId, data, onRefresh }: { placeId: string; data: HistoryData; onRefresh?: () => void }) {
  const [tab, setTab] = useState<Tab>('architecture');
  const place = data.places.find((p) => p.id === placeId);
  if (!place) return <div className="inspector-body inspector-empty">Place not found.</div>;

  const figureName = new Map(data.figures.map((f) => [f.id, f]));
  const founder = place.founding_figure_id ? figureName.get(place.founding_figure_id) : null;
  const owner = place.current_owner_figure_id ? figureName.get(place.current_owner_figure_id) : null;
  const media = data.media[place.id] ?? [];

  return (
    <>
      <div className="inspector-header">
        <div className="inspector-title">{place.name}</div>
        <div className="inspector-subtitle">
          {place.place_type} · {place.status}
        </div>
      </div>
      <div className="inspector-tabs">
        {(['architecture', 'history', 'ownership', 'media'] as Tab[]).map((t) => (
          <button key={t} className={`inspector-tab ${tab === t ? 'is-active' : ''}`} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>
      <div className="inspector-body">
        {tab === 'architecture' && (
          <div>
            <div className="inspector-kv">
              founded <b>{place.founded_year}</b>
              {place.closed_year ? (
                <>
                  {' '}
                  · closed <b>{place.closed_year}</b>
                </>
              ) : null}
            </div>
            <p>{place.architecture}</p>
            {(place.properties.tags ?? []).length > 0 && (
              <div className="inspector-kv">tags: {[...new Set(place.properties.tags)].join(', ')}</div>
            )}
          </div>
        )}
        {tab === 'history' && (
          <div>
            {place.history.length === 0 && <div className="inspector-empty">No recorded history.</div>}
            {place.history.map((h, i) => (
              <div className="inspector-entry" key={i}>
                <span className="inspector-entry-year">{h.year}</span>
                {h.gospel_text}
              </div>
            ))}
          </div>
        )}
        {tab === 'ownership' && (
          <div>
            <div className="inspector-kv">
              <b>founded by</b> {founder ? `${founder.name} (${founder.role})` : '—'}
            </div>
            <div className="inspector-kv">
              <b>current owner</b> {owner ? `${owner.name} (${owner.role})` : '—'}
            </div>
          </div>
        )}
        {tab === 'media' && <MediaGrid items={media} entityId={place.id} onDeleted={onRefresh} />}
      </div>
    </>
  );
}
