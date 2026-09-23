import { useState } from 'react';
import { city } from '../api/client';
import type { MediaItem } from '../api/types';
import { useLightboxStore } from '../state/lightboxStore';

// `entityId` + `onDeleted` are optional so this can still render read-only
// (no delete affordance) wherever a caller doesn't have a clear owner to
// refresh afterward -- every current caller (AgentDetail/PlaceDetail)
// passes both, but nothing here assumes it always will.
export function MediaGrid({ items, entityId, onDeleted }: { items: MediaItem[]; entityId?: string; onDeleted?: () => void }) {
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const openLightbox = useLightboxStore((s) => s.open);

  if (items.length === 0) return <div className="inspector-empty">No media generated yet.</div>;

  async function handleDelete(mediaId: string) {
    if (!entityId) return;
    if (!window.confirm('Delete this media? This removes the file permanently.')) return;
    setDeletingId(mediaId);
    try {
      await city.removeMedia(entityId, mediaId);
      onDeleted?.();
    } catch (e) {
      console.error('failed to delete media', e);
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="inspector-media-grid">
      {items.map((item) => (
        <div className="inspector-media-item" key={item.id} title={item.prompt}>
          {item.kind === 'video' ? (
            <video src={city.fileUrl(item.url)} controls />
          ) : (
            <img
              src={city.fileUrl(item.url)}
              alt={item.prompt}
              className="is-expandable"
              onClick={() => openLightbox(city.fileUrl(item.url))}
            />
          )}
          {entityId && (
            <button
              className="inspector-media-delete"
              title="Delete"
              disabled={deletingId === item.id}
              onClick={() => handleDelete(item.id)}
            >
              ✕
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
