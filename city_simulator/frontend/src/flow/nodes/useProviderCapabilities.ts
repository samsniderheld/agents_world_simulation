// Which visuals providers exist, what each can do, and each kind's default
// (GET /api/visuals/providers) -- for the Image/Video nodes' provider
// pickers and for greying out controls a provider can't honor. Fetched once
// per page load and shared; it only changes when the server restarts.
import { useEffect, useState } from 'react';
import { visuals } from '../../api/client';
import type { ProviderCapabilities, VisualsProviders } from '../../api/types';

let cached: Promise<VisualsProviders | null> | null = null;

export function useVisualsProviders(): VisualsProviders | null {
  const [info, setInfo] = useState<VisualsProviders | null>(null);
  useEffect(() => {
    let cancelled = false;
    cached ??= visuals.providers().catch(() => {
      cached = null;
      return null;
    });
    cached.then((res) => !cancelled && setInfo(res));
    return () => {
      cancelled = true;
    };
  }, []);
  return info;
}

// What `provider` (or, when blank, the default for `kind`) can do.
export function useProviderCapabilities(kind: 'image' | 'video' = 'image', provider?: string): ProviderCapabilities | null {
  const info = useVisualsProviders();
  if (!info) return null;
  return info.capabilities[provider || info.defaults[kind]] ?? null;
}
