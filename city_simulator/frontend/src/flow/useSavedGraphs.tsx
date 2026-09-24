// The "Saved graphs" drawer section plus its two small dialogs (name a save;
// add-or-replace on load) -- one hook every canvas calls, so each only has
// to append `section` to its drawer and render `modal`.
import { useState } from 'react';
import type { GraphDoc } from '../api/types';
import { SavedGraphDialog, type SavedGraphDialogKind } from './SavedGraphDialog';
import type { DrawerSection } from './SideDrawer';
import { useGraphLibrary } from './useGraphLibrary';

export function useSavedGraphs(scope: string, persisted: { flush: () => Promise<void>; adopt: (doc: GraphDoc) => void }) {
  const { saved, saveCurrent, load, remove } = useGraphLibrary(scope, persisted);
  const [dialog, setDialog] = useState<SavedGraphDialogKind | null>(null);

  const section: DrawerSection = {
    id: 'saved-graphs',
    label: 'Saved graphs',
    items: [
      { id: 'save-current', label: '+ Save this canvas', sublabel: 'keep a named copy to load later', dragPayload: 'library:save', onAdd: () => setDialog({ kind: 'save' }) },
      ...saved.map((g) => ({
        id: g.id,
        label: g.name,
        sublabel: `${g.node_count} node${g.node_count === 1 ? '' : 's'}${g.storyboard_count ? `, ${g.storyboard_count} storyboard${g.storyboard_count === 1 ? '' : 's'}` : ''} · ${new Date(g.created).toLocaleDateString()}`,
        dragPayload: `library:${g.id}`,
        onAdd: () => setDialog({ kind: 'load', id: g.id, name: g.name }),
        onDelete: () => {
          if (window.confirm(`Delete saved graph "${g.name}"? Canvases it was loaded into keep their copies.`)) {
            remove(g.id).catch((e) => console.error('failed to delete saved graph', e));
          }
        },
      })),
    ],
  };

  const modal = dialog && (
    <SavedGraphDialog
      dialog={dialog}
      onClose={() => setDialog(null)}
      onSave={saveCurrent}
      onLoad={(mode) => (dialog.kind === 'load' ? load(dialog.id, mode) : Promise.resolve())}
    />
  );

  return { section, modal };
}
