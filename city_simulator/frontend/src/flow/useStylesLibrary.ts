// The global style library (visuals/styles.py) is independent of any one
// canvas -- every canvas's Styles drawer section lists the same entries,
// so a style saved on one screen (e.g. "Edward Hopper" on the city
// canvas) shows up as a pickable item everywhere else, not just as a
// dead-end you have to recreate from scratch.
import { useCallback, useEffect, useState } from 'react';
import { stylesApi } from '../api/client';
import type { Style } from '../api/types';

export function useStylesLibrary() {
  const [styles, setStyles] = useState<Style[]>([]);

  const refresh = useCallback(() => {
    stylesApi
      .list()
      .then((res) => setStyles(res.styles))
      .catch(() => {});
  }, []);

  useEffect(refresh, [refresh]);

  // Removes the library entry and refreshes -- any canvas node still
  // pointing at this styleId (StyleNode.tsx's `style not found in
  // library` state) is left for the user to deal with explicitly, same
  // as MissingNode does for a deleted agent/place.
  const remove = useCallback((id: string) => stylesApi.remove(id).then(refresh), [refresh]);

  return { styles, refresh, remove };
}
