// A typed port -- 9px square (not React Flow's default circle), colored
// by port type per the design spec's token set. Both the Handle and its
// label position absolutely relative to React Flow's own `.react-flow__
// node` wrapper (so they must render with no *positioned* ancestor in
// between -- see nodes.css's `.node-shell`/`.node-body`, deliberately
// left un-positioned). No connection is functionally wired up yet
// (Simulation/Treatment/Style node types don't exist until Phase 2-4), so
// this is the visual anchor the future pipeline will use, not a working
// connection today.
import { Handle, Position } from '@xyflow/react';
import type { PortType } from './portTypes';
import { portColor } from './portTypes';

interface PortProps {
  id: string;
  type: PortType;
  direction: 'in' | 'out';
  label: string;
  // A CSS length, e.g. "calc(100% - 14px)" to anchor from the node's
  // bottom edge -- collapsed node height varies with content, so ports
  // are placed relative to the bottom (where the design's footer row
  // lives) rather than a fixed offset from the top that would land
  // inside the header on shorter nodes.
  top: string;
  optional?: boolean;
}

export function Port({ id, type, direction, label, top, optional }: PortProps) {
  const color = portColor(type);
  const isIn = direction === 'in';
  return (
    <>
      <Handle
        id={id}
        type={isIn ? 'target' : 'source'}
        position={isIn ? Position.Left : Position.Right}
        className="node-port"
        style={{ top, background: optional ? 'transparent' : color, borderColor: color }}
      />
      <span className="node-port-label" style={{ top: `calc(${top} - 6px)`, [isIn ? 'left' : 'right']: 12 }}>
        {label}
      </span>
    </>
  );
}
