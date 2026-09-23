import type { AgentEvent } from '../api/types';

export function fmtDate(iso?: string | null): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

// Every event kind has different fields (see agents/recorder.py's
// docstring) -- this is the one place that knows how to turn each into a
// single readable line for the flattened event log.
export function eventLine(e: AgentEvent): string {
  switch (e.kind) {
    case 'plan':
      return (e.items ?? []).join(' → ') || 'made a plan';
    case 'decompose':
      return `${e.broad_step ?? ''}: ${(e.items ?? []).join(', ')}`;
    case 'action':
      return `${e.text ?? ''}${e.location ? ` (@ ${e.location})` : ''}`;
    case 'dialogue':
      return `${e.text ?? ''}${e.listener ? ` → ${e.listener}` : ''}`;
    case 'move':
      return `${e.from_location ?? '?'} → ${e.to_location ?? '?'}`;
    case 'memory':
      return e.text ?? '';
    case 'observe':
    case 'react':
    case 'focal':
    case 'insight':
    case 'treatment':
      return e.text ?? '';
    case 'continue':
      return 'continued';
    case 'reflect_pause':
      return 'paused to reflect';
    default:
      return '';
  }
}
