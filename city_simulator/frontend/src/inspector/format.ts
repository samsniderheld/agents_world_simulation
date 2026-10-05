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
    case 'check':
      // "pick the lock · DEX 7+2=9 vs 15 -- failure"; an opposed check's
      // text already names the move ("persuade Sal: CHA ... vs WIS 12 ...")
      return e.opposed_by ? String(e.text ?? '') : `${e.action ?? ''} · ${e.text ?? ''}`;
    case 'outcome': {
      const effects = Array.isArray(e.effects) && e.effects.length ? ` [${(e.effects as string[]).join(', ')}]` : '';
      return `${e.text ?? ''}${e.feeling ? ` — feels ${e.feeling}` : ''}${effects}`;
    }
    case 'continue':
      return 'continued';
    case 'reflect_pause':
      return 'paused to reflect';
    case 'status':
    case 'encounter':
    case 'promotion':
    case 'schedule':
    case 'schedules':
    case 'moves':
    case 'tick_summary':
    case 'checks':
    case 'metrics':
      return e.text ?? '';
    default:
      return '';
  }
}

// "success" | "failure" for a check/outcome event (crits included), for
// colouring its log badge; undefined for everything else.
export function eventOutcome(e: AgentEvent): 'success' | 'failure' | undefined {
  if (e.kind !== 'check' && e.kind !== 'outcome') return undefined;
  const o = String(e.outcome ?? '');
  if (o.endsWith('success')) return 'success';
  if (o.endsWith('failure')) return 'failure';
  return undefined;
}
