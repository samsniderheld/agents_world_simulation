// The two small dialogs behind the drawer's "Saved graphs" section: name a
// save, or choose add-or-replace on load. See useSavedGraphs.tsx.
import { useState } from 'react';
import './newAgentModal.css';
import type { LoadMode } from './useGraphLibrary';

export type SavedGraphDialogKind = { kind: 'save' } | { kind: 'load'; id: string; name: string };

export function SavedGraphDialog({
  dialog,
  onClose,
  onSave,
  onLoad,
}: {
  dialog: SavedGraphDialogKind;
  onClose: () => void;
  onSave: (name: string) => Promise<void>;
  onLoad: (mode: LoadMode) => Promise<void>;
}) {
  const [name, setName] = useState('');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(fn: () => Promise<void>) {
    setPending(true);
    setError(null);
    try {
      await fn();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>{dialog.kind === 'save' ? 'Save this canvas' : `Load "${dialog.name}"`}</h3>
          <button className="modal-close" title="Close" onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="modal-body">
          {dialog.kind === 'save' ? (
            <>
              <label className="modal-field">
                <span>Name</span>
                <input
                  autoFocus
                  value={name}
                  placeholder="e.g. Market chase setup"
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && name.trim() && !pending && act(() => onSave(name.trim()))}
                />
              </label>
              <div className="modal-hint">
                Saves every node and connection on this canvas, including what's inside its Storyboards. It keeps
                autosaving as usual; this is a separate named copy.
              </div>
            </>
          ) : (
            <div className="modal-hint">
              <b>Add to canvas</b> places a copy to the right of what's here. <b>Replace canvas</b> removes everything
              on this canvas first. Either way the copy is independent: editing it never changes the saved graph.
            </div>
          )}
          {error && <div className="modal-error">{error}</div>}
        </div>
        <div className="modal-actions">
          <button className="node-run-btn" onClick={onClose}>
            Cancel
          </button>
          {dialog.kind === 'save' ? (
            <button className="node-run-btn" disabled={pending || !name.trim()} onClick={() => act(() => onSave(name.trim()))}>
              {pending ? 'saving…' : 'Save'}
            </button>
          ) : (
            <>
              <button className="node-run-btn" disabled={pending} onClick={() => act(() => onLoad('replace'))}>
                Replace canvas
              </button>
              <button className="node-run-btn" disabled={pending} onClick={() => act(() => onLoad('add'))}>
                {pending ? 'loading…' : 'Add to canvas'}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
