// The single table `isValidConnection` and the "add connected node" menu
// both consult (per the design spec) -- source handle id -> the target
// handle ids it may plug into. Handle ids are the same strings each
// node's <Port id="..."/> uses, so this is the one place the pipeline's
// shape is declared.
const ALLOWED: Record<string, string[]> = {
  // 'agents:in' is Simulation's multi-agent slot; 'agent:in' is Image/
  // Frame's single-agent reference-image slot -- same source handle, two
  // different meanings depending on what it's plugged into.
  'agent:out': ['agents:in', 'agent:in'],
  'place:out': ['place:in'],
  'run:out': ['run:in'],
  'shots:out': ['shot:in'],
  'image:out': ['image:in'],
  'style:out': ['style:in'],
  'treatment:out': ['text:in'],
};

export function isValidConnection(sourceHandle: string | null | undefined, targetHandle: string | null | undefined): boolean {
  if (!sourceHandle || !targetHandle) return false;
  return ALLOWED[sourceHandle]?.includes(targetHandle) ?? false;
}
