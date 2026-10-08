import { useState } from 'react';

// A plain text box rather than <input type="number">: Chrome changes a
// focused number input when you scroll over it, and with scroll panning the
// canvas that silently ran a 7-tick setting down to 1. What you type is kept
// as typed (no snapping to the minimum mid-edit) and applied -- clamped to
// min..max (no upper limit when `max` is omitted) -- when you leave the field
// or press Enter.
export function NumberField({ value, min, max = Infinity, title, onCommit }: { value: number; min: number; max?: number; title: string; onCommit: (v: number) => void }) {
  const [draft, setDraft] = useState(String(value));
  const [shown, setShown] = useState(value);
  if (value !== shown) {
    setShown(value);
    setDraft(String(value));
  }
  function commit() {
    const n = Number.parseInt(draft, 10);
    const next = Number.isNaN(n) ? value : Math.min(max, Math.max(min, n));
    setDraft(String(next));
    if (next !== value) onCommit(next);
  }
  return (
    <input
      className="node-ticks-input nodrag"
      type="text"
      inputMode="numeric"
      value={draft}
      title={max === Infinity ? `${title} (${min} or more)` : `${title} (${min}-${max})`}
      onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ''))}
      onBlur={commit}
      onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
    />
  );
}
