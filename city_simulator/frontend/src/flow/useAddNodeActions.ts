// Every "+ X" action the SideDrawer can trigger, shared across every
// canvas that offers the full node palette. `data` is nullable: a canvas
// with no city context at all (a Scratch board when nothing's ever been
// activated) just gets empty Agents/Locations sections and a no-op
// addNewAgent -- nothing here assumes a city exists.
import { useCallback } from 'react';
import type { Node, XYPosition } from '@xyflow/react';
import { history, stylesApi } from '../api/client';
import type { HistoryData } from '../api/types';
import { toEntityRenderNode } from './entityNodeKit';
import { newNodeId } from './graphIds';
import { gridPosition } from './layout';
import type { PipelineCallbacks } from './pipeline';

export interface AddNodeActionsOptions {
  data: HistoryData | null;
  setNodes: (fn: (prev: Node[] | null) => Node[] | null) => void;
  onExpandAgent: (id: string) => void;
  onExpandPlace: (id: string) => void;
  onRemoveMissing: (nodeId: string) => void;
  onDataRefresh?: () => void;
  pipeline: PipelineCallbacks;
  onImageUpdate: (nodeId: string, patch: { prompt?: string; url?: string; localPath?: string }) => void;
  onMusicUpdate: (nodeId: string, patch: { prompt?: string; negativePrompt?: string; url?: string }) => void;
}

const PIPELINE_TYPES = new Set(['sim', 'treatment', 'frame', 'video', 'style']);

export function useAddNodeActions({
  data,
  setNodes,
  onExpandAgent,
  onExpandPlace,
  onRemoveMissing,
  onDataRefresh,
  pipeline,
  onImageUpdate,
  onMusicUpdate,
}: AddNodeActionsOptions) {
  const addToCanvas = useCallback(
    (entry: { id: string; kind: 'agent' | 'location' }, position?: XYPosition) => {
      if (!data) return;
      setNodes((prev) => {
        const list = prev ?? [];
        const pos = position ?? gridPosition(list.length, { columns: 4, cellWidth: 270, cellHeight: 190 });
        const built =
          entry.kind === 'agent'
            ? toEntityRenderNode({ id: `agent:${entry.id}`, type: 'agent', position: pos, data: { characterId: entry.id } }, data, onExpandAgent, onExpandPlace, onRemoveMissing)
            : toEntityRenderNode({ id: `place:${entry.id}`, type: 'location', position: pos, data: { placeId: entry.id } }, data, onExpandAgent, onExpandPlace, onRemoveMissing);
        return built ? [...list, built] : list;
      });
    },
    [data, setNodes, onExpandAgent, onExpandPlace, onRemoveMissing],
  );

  const addPipelineNode = useCallback(
    (type: 'sim' | 'treatment' | 'video', position?: XYPosition) => {
      setNodes((prev) => {
        const list = prev ?? [];
        const pos =
          position ??
          gridPosition(list.filter((n) => PIPELINE_TYPES.has(n.type ?? '')).length, { columns: 3, cellWidth: 340, cellHeight: 260, originY: 900 });
        const id = newNodeId(type);
        const base = { id, position: pos };
        if (type === 'sim') return [...list, { ...base, type, data: { ticks: 8, agentNames: [], onTicksChange: pipeline.onTicksChange } }];
        if (type === 'treatment')
          return [
            ...list,
            { ...base, type, data: { candidates: [], onSubjectChange: pipeline.onSubjectChange, onGenerated: pipeline.onTreatmentGenerated, onEmitFrames: pipeline.onEmitFrames } },
          ];
        return [...list, { ...base, type, data: { prompt: '', onUpdate: pipeline.onVideoUpdate } }];
      });
    },
    [setNodes, pipeline],
  );

  // Styles live in the global library (visuals/styles.py), not the graph
  // document -- "+ Style" always mints a fresh library entry rather than
  // opening a picker over existing ones, a deliberate v1 scope cut (see
  // the design spec's own note that a style authored elsewhere should be
  // selectable here -- worth adding once there's more than one style to
  // pick from in practice).
  const addStyleNode = useCallback(
    async (position?: XYPosition) => {
      let created;
      try {
        created = await stylesApi.create({ name: 'New Style', stylePrompt: '' });
      } catch (e) {
        console.error('failed to create style', e);
        return;
      }
      setNodes((prev) => {
        const list = prev ?? [];
        const pos =
          position ??
          gridPosition(list.filter((n) => PIPELINE_TYPES.has(n.type ?? '')).length, { columns: 3, cellWidth: 340, cellHeight: 260, originY: 900 });
        return [
          ...list,
          {
            id: newNodeId('style'),
            type: 'style',
            position: pos,
            data: { styleId: created.style.id, style: created.style, onLoaded: pipeline.onStyleLoaded, onUpdate: pipeline.onStyleUpdate },
          },
        ];
      });
    },
    [setNodes, pipeline],
  );

  // The one node type backed by something that doesn't exist until you
  // add it -- generates a real character (grounded in a random place,
  // same as the old app's "Generate Character") and persists it
  // immediately, then adds the node using the record just returned
  // rather than waiting for `data` to refetch.
  const addNewAgent = useCallback(
    async (position?: XYPosition) => {
      if (!data) return;
      let saved;
      try {
        const preview = await history.previewCharacter({});
        saved = (await history.createCharacter(preview.character)).character;
      } catch (e) {
        console.error('failed to create agent', e);
        return;
      }
      setNodes((prev) => {
        const list = prev ?? [];
        const pos = position ?? gridPosition(list.length, { columns: 4, cellWidth: 270, cellHeight: 190 });
        const dataWithNewCharacter: HistoryData = { ...data, characters: [...data.characters, saved] };
        const built = toEntityRenderNode(
          { id: `agent:${saved.id}`, type: 'agent', position: pos, data: { characterId: saved.id } },
          dataWithNewCharacter,
          onExpandAgent,
          onExpandPlace,
          onRemoveMissing,
        );
        return built ? [...list, built] : list;
      });
      onDataRefresh?.();
    },
    [data, setNodes, onExpandAgent, onExpandPlace, onRemoveMissing, onDataRefresh],
  );

  // scratch-image/scratch-music are ungrounded (no citystate entity), so
  // they're valid to drop on any canvas, not just a Scratch board.
  const addScratchNode = useCallback(
    (type: 'scratch-image' | 'scratch-music', position?: XYPosition) => {
      setNodes((prev) => {
        const list = prev ?? [];
        const pos = position ?? gridPosition(list.length, { columns: 4, cellWidth: 280, cellHeight: 240 });
        const id = newNodeId(type);
        if (type === 'scratch-image') return [...list, { id, type, position: pos, data: { prompt: '', onUpdate: onImageUpdate } }];
        return [...list, { id, type, position: pos, data: { prompt: '', negativePrompt: '', onUpdate: onMusicUpdate } }];
      });
    },
    [setNodes, onImageUpdate, onMusicUpdate],
  );

  return { addToCanvas, addPipelineNode, addStyleNode, addNewAgent, addScratchNode, PIPELINE_TYPES };
}
