import type { Node } from '@xyflow/react';

// Shared by every canvas's <MiniMap nodeColor={...}> -- roughly follows
// the same port-type color families (theme/tokens.css's --port-*) so the
// minimap reads as an extension of the canvas, not a generic overlay.
export function miniMapNodeColor(n: Node): string {
  switch (n.type) {
    case 'agent':
    case 'location':
      return 'var(--port-entity)';
    case 'sim':
      return 'var(--node-running)';
    case 'treatment':
      return 'var(--port-narrative)';
    case 'frame':
    case 'image':
    case 'scratch-image':
      return 'var(--port-media)';
    case 'video':
      return 'var(--port-media)';
    case 'style':
      return 'var(--port-style)';
    case 'scratch-music':
      return 'var(--port-narrative)';
    case 'missing':
      return 'var(--node-error)';
    default:
      return 'var(--node-border)';
  }
}
