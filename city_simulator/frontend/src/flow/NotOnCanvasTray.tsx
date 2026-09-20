import './tray.css';

export interface TrayEntry {
  id: string;
  label: string;
}

export function NotOnCanvasTray<T extends TrayEntry>({ entries, onAdd }: { entries: T[]; onAdd: (entry: T) => void }) {
  if (entries.length === 0) return null;
  return (
    <div className="canvas-tray">
      <div className="canvas-tray-label">Not on canvas</div>
      {entries.map((e) => (
        <button key={e.id} className="canvas-tray-item" onClick={() => onAdd(e)}>
          + {e.label}
        </button>
      ))}
    </div>
  );
}
