import { city } from '../api/client';
import type { MediaItem } from '../api/types';

export function MediaGrid({ items }: { items: MediaItem[] }) {
  if (items.length === 0) return <div className="inspector-empty">No media generated yet.</div>;
  return (
    <div className="inspector-media-grid">
      {items.map((item) => (
        <div className="inspector-media-item" key={item.id} title={item.prompt}>
          {item.kind === 'video' ? (
            <video src={city.fileUrl(item.url)} controls />
          ) : (
            <img src={city.fileUrl(item.url)} alt={item.prompt} />
          )}
        </div>
      ))}
    </div>
  );
}
