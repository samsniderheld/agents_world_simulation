// scratch-image/scratch-music <-> persisted-shape mapping -- these two
// are "ungrounded" (no citystate entity), so they're just as valid on
// CityCanvas or an entity's own canvas as on a Scratch board; shared here
// once more than ScratchScreen needed them.
import type { Node } from '@xyflow/react';
import type { GraphNode } from '../api/types';
import type { ScratchImageNodeData } from './nodes/ScratchImageNode';
import type { ScratchMusicNodeData } from './nodes/ScratchMusicNode';

export function toScratchRenderNode(
  gn: GraphNode,
  onImageUpdate: ScratchImageNodeData['onUpdate'],
  onMusicUpdate: ScratchMusicNodeData['onUpdate'],
): Node | null {
  if (gn.type === 'scratch-image') {
    return {
      id: gn.id,
      type: 'scratch-image',
      position: gn.position,
      // Same explicit floor as Frame/Video/Image's own render-node
      // builders (see pipeline.ts) -- without it a never-resized node
      // shrink-to-fits its own content independently of its siblings.
      width: gn.width ?? 540,
      height: gn.height ?? 430,
      data: { prompt: (gn.data.prompt as string) ?? '', url: gn.data.url as string | undefined, localPath: gn.data.localPath as string | undefined, onUpdate: onImageUpdate },
    };
  }
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
  if (n.type === 'scratch-image') {
    const d = n.data as ScratchImageNodeData;
    return { id: n.id, type: 'scratch-image', position: n.position, width: n.width, height: n.height, data: { prompt: d.prompt, url: d.url, localPath: d.localPath } };
  }
  if (n.type === 'scratch-music') {
    const d = n.data as ScratchMusicNodeData;
    return { id: n.id, type: 'scratch-music', position: n.position, width: n.width, height: n.height, data: { prompt: d.prompt, negativePrompt: d.negativePrompt, url: d.url } };
  }
  return null;
}
