// How every canvas responds to mouse/trackpad input, in one place so the
// four canvases (City, Agent/Place, Scratch, Storyboard) always agree.
//
// Figma-style: dragging on empty canvas draws a selection box (anything it
// touches is selected; Delete/Backspace removes the selection), so panning
// moves to two-finger scroll, Space + drag, or the middle/right mouse
// button. Pinch or ⌘/Ctrl + scroll zooms.
import { SelectionMode } from '@xyflow/react';

export const canvasInteractionProps = {
  selectionOnDrag: true,
  selectionMode: SelectionMode.Partial,
  panOnDrag: [1, 2],
  panOnScroll: true,
  deleteKeyCode: ['Backspace', 'Delete'],
};
