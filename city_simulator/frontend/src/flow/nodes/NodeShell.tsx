import type { ReactNode } from 'react';
import { NodeResizer } from '@xyflow/react';
import './nodes.css';

interface NodeShellProps {
  typeLabel: string;
  selected?: boolean;
  running?: boolean;
  error?: boolean;
  wide?: boolean;
  onExpand?: () => void;
  // Overrides the default resize floor -- Frame/Image/Video/ScratchImage
  // pass a larger one so the drag handles can't shrink the node past what
  // their .node-media-box (locked at min 512x288, see nodes.css) needs;
  // without this, min-width/min-height on the box would fight the node's
  // own resized-smaller width, overflowing instead of just not shrinking.
  minWidth?: number;
  minHeight?: number;
  children: ReactNode;
}

// Resize handles show only while selected (matching the existing
// .is-selected border highlight) so the canvas isn't cluttered with
// handles on every node all the time. The default minWidth/minHeight are
// the same floor nodes.css's min-width/min-height give every node --
// below that, content starts clipping rather than the node meaningfully
// shrinking.
export function NodeShell({ typeLabel, selected, running, error, wide, onExpand, minWidth, minHeight, children }: NodeShellProps) {
  const stateClass = error ? 'is-error' : running ? 'is-running' : selected ? 'is-selected' : '';
  return (
    <div className={`node-shell ${wide ? 'is-wide' : ''} ${stateClass}`}>
      <NodeResizer
        isVisible={selected}
        minWidth={minWidth ?? (wide ? 300 : 240)}
        minHeight={minHeight ?? 60}
        handleClassName="node-resize-handle"
        lineClassName="node-resize-line"
      />
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
