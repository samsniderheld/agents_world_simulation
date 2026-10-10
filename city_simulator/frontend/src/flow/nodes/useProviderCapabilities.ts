// Which visuals providers exist, what each can do, and each kind's default
// (GET /api/visuals/providers) -- for the Image/Video nodes' provider
// pickers and for greying out controls a provider can't honor. Fetched once
// per page load and shared; it only changes when the server restarts.
import { useEffect, useState } from 'react';
import { visuals } from '../../api/client';
import type { ProviderCapabilities, VisualsProviders } from '../../api/types';

let cached: Promise<VisualsProviders | null> | null = null;
const listeners = new Set<(info: VisualsProviders | null) => void>();

function load() {
  cached ??= visuals.providers().catch(() => {
    cached = null;
    return null;
  });
  return cached;
}

// Re-fetch (e.g. after a node made its ComfyUI address the default) and
// update every node showing it.
export function refreshVisualsProviders() {
  cached = null;
  load().then((info) => listeners.forEach((fn) => fn(info)));
}

export function useVisualsProviders(): VisualsProviders | null {
  const [info, setInfo] = useState<VisualsProviders | null>(null);
  useEffect(() => {
    let cancelled = false;
    const listener = (next: VisualsProviders | null) => !cancelled && setInfo(next);
    listeners.add(listener);
    load().then(listener);
    return () => {
      cancelled = true;
      listeners.delete(listener);
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
