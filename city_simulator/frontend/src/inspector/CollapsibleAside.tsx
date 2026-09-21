import { useState } from 'react';
import type { ReactNode } from 'react';
import './inspector.css';

// Shared by Inspector (the city canvas) and the Agent/Place drill-in
// screens (which render their own detail panel directly, not through
// Inspector) -- one place owns the closed/open toggle so both don't
// drift into different behaviors.
export function CollapsibleAside({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <button className="inspector-expand-tab" onClick={() => setCollapsed(false)} title="Show panel">
        ◀
      </button>
    );
  }

  return (
    <aside className="inspector">
      <button className="inspector-close-btn" onClick={() => setCollapsed(true)} title="Hide panel">
        ✕
      </button>
      {children}
    </aside>
  );
}
