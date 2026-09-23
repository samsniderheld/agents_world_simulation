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

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

function rectsOverlap(a: Rect, b: Rect, margin: number): boolean {
  return a.x < b.x + b.width + margin && a.x + a.width + margin > b.x && a.y < b.y + b.height + margin && a.y + a.height + margin > b.y;
}

// Like gridPosition, but skips any cell that would overlap an existing
// node (an "emit frames"-style batch drop needs to land somewhere real,
// not just avoid overlapping the *other* frames in the same batch) --
// scans the grid in reading order, extending downward as many rows as it
// takes to find `count` free cells, rather than a real bin-packer. Good
// enough for "don't overlap, leave a gap" -- not trying to be compact.
export function nonOverlappingGridPositions(
  count: number,
  opts: { itemWidth: number; itemHeight: number; columns: number; gutter: number; originX: number; originY: number },
  obstacles: Rect[],
): { x: number; y: number }[] {
  const { itemWidth, itemHeight, columns, gutter, originX, originY } = opts;
  const cellWidth = itemWidth + gutter;
  const cellHeight = itemHeight + gutter;
  const placed: Rect[] = [];
  const results: { x: number; y: number }[] = [];
  let index = 0;
  const maxSlots = Math.max(count * 6, columns * 60);
  while (results.length < count && index < maxSlots) {
    const col = index % columns;
    const row = Math.floor(index / columns);
    const candidate: Rect = { x: originX + col * cellWidth, y: originY + row * cellHeight, width: itemWidth, height: itemHeight };
    const blocked = [...obstacles, ...placed].some((o) => rectsOverlap(candidate, o, gutter));
    if (!blocked) {
      placed.push(candidate);
      results.push({ x: candidate.x, y: candidate.y });
    }
    index += 1;
  }
  return results;
}
