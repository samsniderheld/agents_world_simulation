import type { ReactNode } from 'react';
import './nodes.css';

interface NodeShellProps {
  typeLabel: string;
  selected?: boolean;
  running?: boolean;
  error?: boolean;
  wide?: boolean;
  onExpand?: () => void;
  children: ReactNode;
}

export function NodeShell({ typeLabel, selected, running, error, wide, onExpand, children }: NodeShellProps) {
  const stateClass = error ? 'is-error' : running ? 'is-running' : selected ? 'is-selected' : '';
  return (
    <div className={`node-shell ${wide ? 'is-wide' : ''} ${stateClass}`}>
      <div className="node-header">
        <span>{typeLabel}</span>
        {onExpand && (
          <button
            className="node-expand"
            title="Expand"
            onClick={(e) => {
              e.stopPropagation();
              onExpand();
            }}
          >
            ⤢
          </button>
        )}
      </div>
      <div className="node-body">{children}</div>
    </div>
  );
}
