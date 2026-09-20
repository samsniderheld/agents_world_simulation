import type { Node, NodeProps } from '@xyflow/react';
import type { Place } from '../../api/types';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface LocationNodeData extends Record<string, unknown> {
  place: Place;
  thumbUrl?: string;
  residentCount: number;
  onExpand: (placeId: string) => void;
}

export type LocationNodeType = Node<LocationNodeData, 'location'>;

export function LocationNode({ data, selected }: NodeProps<LocationNodeType>) {
  const { place, thumbUrl, residentCount, onExpand } = data;
  const years = place.closed_year ? `${place.founded_year}–${place.closed_year}` : `${place.founded_year}`;

  return (
    <NodeShell typeLabel="Location" selected={selected} onExpand={() => onExpand(place.id)}>
      <div className="node-thumb-row">
        <div className="node-thumb">{thumbUrl ? <img src={thumbUrl} alt="" /> : '▤'}</div>
        <div>
          <div className="node-title">{place.name}</div>
          <div className="node-subtitle">
            {place.place_type} · {years}
          </div>
        </div>
      </div>
      <div className="node-grounding">
        {place.status}
        {residentCount > 0 ? ` · ${residentCount} resident${residentCount === 1 ? '' : 's'}` : ''}
      </div>

      <Port id="place:out" type="place" direction="out" label="place" top="calc(100% - 14px)" />
      <Port id="style:in" type="style" direction="in" label="style" optional top="calc(100% - 14px)" />
    </NodeShell>
  );
}
