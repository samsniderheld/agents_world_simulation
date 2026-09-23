// Lets a node grey out a control it can't honor instead of failing at
// generate time (per the design spec). Fetched fresh per node rather
// than shared/cached -- this is a small, rarely-changing GET, and every
// node needing it (currently just StyleNode's reference-image upload) is
// cheap to have ask independently.
import { useEffect, useState } from 'react';
import { visuals } from '../../api/client';
import type { ProviderCapabilities } from '../../api/types';

export function useProviderCapabilities(): ProviderCapabilities | null {
  const [capabilities, setCapabilities] = useState<ProviderCapabilities | null>(null);

  useEffect(() => {
    let cancelled = false;
    visuals
      .providers()
      .then((res) => {
        if (!cancelled) setCapabilities(res.capabilities[res.current] ?? null);
      })
      .catch(() => {
        if (!cancelled) setCapabilities(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return capabilities;
}
