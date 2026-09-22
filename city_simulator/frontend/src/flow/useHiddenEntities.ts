// Per-city, per-viewer curation: which Agents/Locations are excluded from
// every canvas's own "+ Agent"/"+ Location" drawer list (their
// notOnCanvasAgents/notOnCanvasLocations). Toggled from the Gallery
// screen (routes/GalleryScreen.tsx), which itself always shows every
// card regardless -- this only thins the drawer, never removes anything
// already placed. Not domain data (nothing server-side cares), so it
// lives in localStorage rather than the graph/citystate -- the first use
// of localStorage in this app, scoped tightly to this one concern.
import { useCallback, useEffect, useState } from 'react';

function storageKey(cityId: string): string {
  return `gallery-hidden:${cityId}`;
}

function readHidden(cityId: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(storageKey(cityId));
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? new Set(parsed.filter((v): v is string => typeof v === 'string')) : new Set();
  } catch {
    return new Set();
  }
}

function writeHidden(cityId: string, ids: Set<string>): void {
  try {
    window.localStorage.setItem(storageKey(cityId), JSON.stringify([...ids]));
  } catch {
    // Private browsing / storage disabled / quota exceeded -- the toggle
    // still works for the rest of this session via React state, it just
    // won't survive a reload. Not worth surfacing to the user.
  }
}

export function useHiddenEntities(cityId: string | undefined): {
  hiddenIds: Set<string>;
  isHidden: (id: string) => boolean;
  toggle: (id: string) => void;
} {
  const [hiddenIds, setHiddenIds] = useState<Set<string>>(() => (cityId ? readHidden(cityId) : new Set()));

  // Re-read whenever the city itself changes (e.g. ScratchScreen's
  // active-city id resolves after its own first render, or the user
  // switches cities) -- without this, the initial empty Set from a
  // still-undefined cityId would never get replaced.
  useEffect(() => {
    setHiddenIds(cityId ? readHidden(cityId) : new Set());
  }, [cityId]);

  const toggle = useCallback(
    (id: string) => {
      if (!cityId) return;
      setHiddenIds((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        writeHidden(cityId, next);
        return next;
      });
    },
    [cityId],
  );

  const isHidden = useCallback((id: string) => hiddenIds.has(id), [hiddenIds]);

  return { hiddenIds, isHidden, toggle };
}
