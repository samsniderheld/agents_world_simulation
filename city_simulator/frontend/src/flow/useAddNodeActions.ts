// Every "+ X" action the SideDrawer can trigger, shared across every
// canvas that offers the full node palette. `data` is nullable: a canvas
// with no city context at all (a Scratch board when nothing's ever been
// activated) just gets empty Agents/Locations sections and a no-op
// addNewAgent -- nothing here assumes a city exists.
import { useCallback } from 'react';
import type { Node, XYPosition } from '@xyflow/react';
import { stylesApi } from '../api/client';
import type { Character, HistoryData, Style } from '../api/types';
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
  // Called after "+ New style" mints a fresh library entry, so a caller
  // holding a separate styles-list fetch (useStylesLibrary) can refresh
  // and show it in the drawer without polling.
  onStyleCreated?: () => void;
  // "+ New agent" doesn't generate/save anything itself anymore -- it
  // opens NewAgentModal (rendered by the caller, which owns that UI
  // concern the same way it owns SideDrawer/Inspector) so the user can
  // pick constraints, preview, and edit before anything is persisted.
  // placeAgentNode below is what actually adds the node, once the modal's
  // own Save has a real saved character in hand.
  onOpenNewAgentModal: (position?: XYPosition) => void;
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
  onStyleCreated,
  onOpenNewAgentModal,
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
    (type: 'sim' | 'treatment' | 'video' | 'text-viewer', position?: XYPosition) => {
      setNodes((prev) => {
        const list = prev ?? [];
        const pos =
          position ??
          gridPosition(list.filter((n) => PIPELINE_TYPES.has(n.type ?? '')).length, { columns: 3, cellWidth: 340, cellHeight: 260, originY: 900 });
        const id = newNodeId(type);
        const base = { id, position: pos };
        if (type === 'sim')
          return [
            ...list,
            {
              ...base,
              type,
              data: {
                ticks: 8,
                directive: '',
                provider: 'ollama',
                chatModel: '',
                verbose: true,
                agentNames: [],
                onTicksChange: pipeline.onTicksChange,
                onDirectiveChange: pipeline.onDirectiveChange,
                onProviderChange: pipeline.onProviderChange,
                onChatModelChange: pipeline.onChatModelChange,
                onVerboseChange: pipeline.onVerboseChange,
              },
            },
          ];
        if (type === 'treatment')
          return [
            ...list,
            {
              ...base,
              type,
              data: {
                candidates: [],
                provider: '',
                model: '',
                onSubjectChange: pipeline.onSubjectChange,
                onGenerated: pipeline.onTreatmentGenerated,
                onEmitFrames: pipeline.onEmitFrames,
                onProviderChange: pipeline.onTreatmentProviderChange,
                onModelChange: pipeline.onTreatmentModelChange,
              },
            },
          ];
        if (type === 'text-viewer') return [...list, { ...base, type, data: {} }];
        return [...list, { ...base, type, data: { prompt: '', onUpdate: pipeline.onVideoUpdate } }];
      });
    },
    [setNodes, pipeline],
  );

  // Styles live in the global library (visuals/styles.py), not the graph
  // document -- passing `existing` points the new node at that library
  // entry directly (the useStylesLibrary-backed drawer section lists
  // every saved style for exactly this); omitting it mints a fresh one,
  // same as "+ New style".
  const addStyleNode = useCallback(
    async (position?: XYPosition, existing?: Style) => {
      let style = existing;
      if (!style) {
        try {
          style = (await stylesApi.create({ name: 'New Style', stylePrompt: '' })).style;
        } catch (e) {
          console.error('failed to create style', e);
          return;
        }
        onStyleCreated?.();
      }
      const resolvedStyle = style;
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
            data: { styleId: resolvedStyle.id, style: resolvedStyle, onLoaded: pipeline.onStyleLoaded, onUpdate: pipeline.onStyleUpdate, onDelete: pipeline.onStyleDelete },
          },
        ];
      });
    },
    [setNodes, pipeline, onStyleCreated],
  );

  // The one node type backed by something that doesn't exist until you
  // add it -- rather than generating+saving a fully random character on
  // the spot, this just opens NewAgentModal at the intended drop
  // position; placeAgentNode below is what the modal's Save calls once a
  // real, user-configured character has actually been persisted.
  const addNewAgent = useCallback(
    (position?: XYPosition) => {
      if (!data) return;
      onOpenNewAgentModal(position);
    },
    [data, onOpenNewAgentModal],
  );

  const placeAgentNode = useCallback(
    (saved: Character, position?: XYPosition) => {
      if (!data) return;
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

  return { addToCanvas, addPipelineNode, addStyleNode, addNewAgent, placeAgentNode, addScratchNode, PIPELINE_TYPES };
}
