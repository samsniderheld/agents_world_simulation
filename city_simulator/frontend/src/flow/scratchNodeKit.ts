// scratch-music <-> persisted-shape mapping -- "ungrounded" (no citystate
// entity), so it's as valid on CityCanvas or an entity's own canvas as on a
// Scratch board. (The freeform "scratch-image" node it used to sit beside
// is now the Image node -- see pipeline.ts's migrateImageNode.)
import type { Node } from '@xyflow/react';
import type { GraphNode } from '../api/types';
import type { ScratchMusicNodeData } from './nodes/ScratchMusicNode';

export function toScratchRenderNode(gn: GraphNode, onMusicUpdate: ScratchMusicNodeData['onUpdate']): Node | null {
  if (gn.type === 'scratch-music') {
    return {
      id: gn.id,
      type: 'scratch-music',
      position: gn.position,
      width: gn.width,
      height: gn.height,
      data: {
        prompt: (gn.data.prompt as string) ?? '',
        negativePrompt: (gn.data.negativePrompt as string) ?? '',
        url: gn.data.url as string | undefined,
        onUpdate: onMusicUpdate,
      },
    };
  }
  return null;
}

export function scratchToGraphNode(n: Node): GraphNode | null {
  if (n.type === 'scratch-music') {
    const d = n.data as ScratchMusicNodeData;
    return { id: n.id, type: 'scratch-music', position: n.position, width: n.width, height: n.height, data: { prompt: d.prompt, negativePrompt: d.negativePrompt, url: d.url } };
  }
  return null;
}
