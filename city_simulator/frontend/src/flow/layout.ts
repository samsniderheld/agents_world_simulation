// A deliberately simple grid placement, not a real layout engine (dagre/
// elkjs) -- per the plan's correction #9, the design spec doesn't do
// timeline/auto-layout at all; positions are user-arranged and persisted,
// so newly-appearing nodes just need *some* non-overlapping starting
// spot until the user drags them wherever they like.
export interface GridOptions {
  columns: number;
  cellWidth: number;
  cellHeight: number;
  originX?: number;
  originY?: number;
}

export function gridPosition(index: number, opts: GridOptions): { x: number; y: number } {
  const { columns, cellWidth, cellHeight, originX = 0, originY = 0 } = opts;
  const col = index % columns;
  const row = Math.floor(index / columns);
  return { x: originX + col * cellWidth, y: originY + row * cellHeight };
}
