// The single table `isValidConnection` and the "add connected node" menu
// both consult (per the design spec) -- source handle id -> the target
// handle ids it may plug into. Handle ids are the same strings each
// node's <Port id="..."/> uses, so this is the one place the pipeline's
// shape is declared.
const ALLOWED: Record<string, string[]> = {
  'agent:out': ['agents:in'],
  'place:out': ['place:in'],
  'run:out': ['run:in'],
  'shots:out': ['shot:in'],
  'image:out': ['image:in'],
  'style:out': ['style:in'],
};

export function isValidConnection(sourceHandle: string | null | undefined, targetHandle: string | null | undefined): boolean {
  if (!sourceHandle || !targetHandle) return false;
  return ALLOWED[sourceHandle]?.includes(targetHandle) ?? false;
}
