// How every canvas responds to mouse/trackpad input, in one place so the
// four canvases (City, Agent/Place, Scratch, Storyboard) always agree.
//
// Figma-style: dragging on empty canvas draws a selection box (anything it
// touches is selected; Delete/Backspace removes the selection), so panning
// moves to two-finger scroll, Space + drag, or the middle/right mouse
// button. Pinch or ⌘/Ctrl + scroll zooms. Click a cord to select it, or drag
// either end of it to move it to another port or drop it to remove it.
import { SelectionMode } from '@xyflow/react';

export const canvasInteractionProps = {
  selectionOnDrag: true,
  selectionMode: SelectionMode.Partial,
  panOnDrag: [1, 2],
  panOnScroll: true,
  deleteKeyCode: ['Backspace', 'Delete'],
  // Grab radius for a cord's end (see useEdgeReconnect.ts); React Flow's
  // default of 10px is fiddly to hit.
  reconnectRadius: 16,
};
