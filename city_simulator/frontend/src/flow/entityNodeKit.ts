// Agent/Location/Missing node <-> persisted-shape mapping, shared by
// every canvas that wants the full node palette (originally CityCanvas-
// only; pulled out here once EntityCanvas and ScratchScreen needed the
// exact same Agent/Location handling -- per the user's explicit
// requirement that every node type be available on every screen, not
// scoped to "wherever it happened to make the most obvious sense").
import type { Node } from '@xyflow/react';
import { city } from '../api/client';
import type { Character, GraphNode, HistoryData, MediaItem, Place } from '../api/types';

export function firstImageUrl(items: MediaItem[] | undefined): string | undefined {
  const hit = items?.find((m) => m.kind === 'image');
  return hit ? city.fileUrl(hit.url) : undefined;
}

export function toEntityRenderNode(
  gn: GraphNode,
  data: HistoryData,
  onExpandAgent: (id: string) => void,
  onExpandPlace: (id: string) => void,
  onRemoveMissing: (nodeId: string) => void,
): Node | null {
  if (gn.type === 'agent') {
    const characterId = gn.data.characterId as string;
    const character = data.characters.find((c) => c.id === characterId);
    if (!character) return null; // reconcile() already routed this to `missing`
    return {
      id: gn.id,
      type: 'agent',
      position: gn.position,
      data: { character, thumbUrl: firstImageUrl(data.media[characterId]), onExpand: onExpandAgent },
    };
  }
  if (gn.type === 'location') {
    const placeId = gn.data.placeId as string;
    const place = data.places.find((p) => p.id === placeId);
    if (!place) return null;
    const residentCount = data.characters.filter((c) => c.place_id === placeId).length;
    return {
      id: gn.id,
      type: 'location',
      position: gn.position,
      data: { place, thumbUrl: firstImageUrl(data.media[placeId]), residentCount, onExpand: onExpandPlace },
    };
  }
  if (gn.type === 'missing') {
    return { id: gn.id, type: 'missing', position: gn.position, data: { entityId: gn.data.entityId as string, onRemove: onRemoveMissing } };
  }
  return null;
}

export function entityToGraphNode(n: Node): GraphNode | null {
  if (n.type === 'agent') {
    const character = (n.data as { character: Character }).character;
    return { id: n.id, type: 'agent', position: n.position, data: { characterId: character.id } };
  }
  if (n.type === 'location') {
    const place = (n.data as { place: Place }).place;
    return { id: n.id, type: 'location', position: n.position, data: { placeId: place.id } };
  }
  if (n.type === 'missing') {
    return { id: n.id, type: 'missing', position: n.position, data: { entityId: (n.data as { entityId: string }).entityId } };
  }
  return null;
}
