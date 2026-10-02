// Every "+ X" action the SideDrawer can trigger, shared across every
// canvas that offers the full node palette. `data` is nullable: a canvas
// with no city context at all (a Scratch board when nothing's ever been
// activated) just gets empty Agents/Locations sections and a no-op
// addNewAgent -- nothing here assumes a city exists.
import { useCallback, useEffect } from 'react';
import type { Edge, Node, XYPosition } from '@xyflow/react';
import { stylesApi } from '../api/client';
import type { Character, CityZoomResult, HistoryData, Style } from '../api/types';
import { toEntityRenderNode } from './entityNodeKit';
import { newNodeId } from './graphIds';
import { gridPosition } from './layout';
import { citySimSettings, type PipelineCallbacks } from './pipeline';

export interface AddNodeActionsOptions {
  data: HistoryData | null;
  setNodes: (fn: (prev: Node[] | null) => Node[] | null) => void;
  // Needed by the City Simulation node's zoom-in, which wires the scene it
  // creates.
  setEdges: (fn: (prev: Edge[]) => Edge[]) => void;
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
  // The agent/place whose own canvas this is, if any: a new Image node
  // saves its results to that entity's media by default.
  ownerEntityId?: string;
  onMusicUpdate: (nodeId: string, patch: { prompt?: string; negativePrompt?: string; url?: string }) => void;
}

const PIPELINE_TYPES = new Set(['sim', 'citysim', 'treatment', 'frame', 'video', 'style', 'storyboard', 'population', 'photo']);

export function useAddNodeActions({
  data,
  setNodes,
  setEdges,
  onExpandAgent,
  onExpandPlace,
  onRemoveMissing,
  onDataRefresh,
  onStyleCreated,
  onOpenNewAgentModal,
  pipeline,
  ownerEntityId,
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
    (type: 'sim' | 'treatment' | 'video' | 'text-viewer' | 'frame' | 'storyboard' | 'population' | 'photo' | 'citysim', position?: XYPosition) => {
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
                tickMinutes: 30,
                startTime: '06:00',
                directive: '',
                provider: 'ollama',
                chatModel: '',
                verbose: true,
                agentNames: [],
                onTicksChange: pipeline.onTicksChange,
                onTickMinutesChange: pipeline.onTickMinutesChange,
                onStartTimeChange: pipeline.onStartTimeChange,
                onDirectiveChange: pipeline.onDirectiveChange,
                onProviderChange: pipeline.onProviderChange,
                onChatModelChange: pipeline.onChatModelChange,
                onVerboseChange: pipeline.onVerboseChange,
              },
            },
          ];
        if (type === 'citysim')
          return [...list, { ...base, type, data: { ...citySimSettings(), agentNames: [], onChange: pipeline.onCitySimChange, onZoomIn: pipeline.onZoomIn } }];
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
                cityPlace: '',
                cityTickFrom: '',
                cityTickTo: '',
                onCityChange: pipeline.onTreatmentCityChange,
                onSubjectChange: pipeline.onSubjectChange,
                onGenerated: pipeline.onTreatmentGenerated,
                onCreateStoryboard: pipeline.onCreateStoryboard,
                onProviderChange: pipeline.onTreatmentProviderChange,
                onModelChange: pipeline.onTreatmentModelChange,
              },
            },
          ];
        if (type === 'text-viewer') return [...list, { ...base, type, data: {} }];
        if (type === 'frame') {
          // The Image node. No shotIndex (that's for storyboard shots), and
          // on an agent's/place's own canvas it saves to that entity's media.
          return [
            ...list,
            {
              ...base,
              type,
              width: 540,
              height: 480,
              data: { prompt: '', attachTo: ownerEntityId, ownerEntityId, onUpdate: pipeline.onFrameUpdate, onCityChanged: pipeline.onCityChanged },
            },
          ];
        }
        if (type === 'photo') {
          return [...list, { ...base, type, width: 540, height: 400, data: { onUpdate: pipeline.onPhotoUpdate } }];
        }
        if (type === 'population') {
          return [
            ...list,
            { ...base, type, width: 340, data: { count: 5, withImages: true, onChange: pipeline.onPopulationChange, onCityChanged: pipeline.onCityChanged } },
          ];
        }
        if (type === 'storyboard') {
          return [
            ...list,
            // width: 340 matches pipeline.ts's toPipelineRenderNode
            // fallback -- see the comment there (same fix Style needed).
            { ...base, type, width: 340, data: { shotCount: 0, contextAgentNames: [], contextPlaceNames: [], contextStyleNames: [], onExpand: pipeline.onExpandStoryboard } },
          ];
        }
        return [...list, { ...base, type, data: { prompt: '', onUpdate: pipeline.onVideoUpdate } }];
      });
    },
    [setNodes, pipeline, ownerEntityId],
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
            // Matches pipeline.ts's toPipelineRenderNode fallback -- a
            // fixed width floor so .style-ref-grid's auto-fill columns
            // have something to wrap within from the moment the node
            // exists, not just after the next reload.
            width: 340,
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

  // scratch-music is ungrounded (no citystate entity), so it's valid to
  // drop on any canvas, not just a Scratch board.
  const addScratchNode = useCallback(
    (type: 'scratch-music', position?: XYPosition) => {
      setNodes((prev) => {
        const list = prev ?? [];
        const pos = position ?? gridPosition(list.length, { columns: 4, cellWidth: 280, cellHeight: 240 });
        return [...list, { id: newNodeId(type), type, position: pos, data: { prompt: '', negativePrompt: '', onUpdate: onMusicUpdate } }];
      });
    },
    [setNodes, onMusicUpdate],
  );

  // A City Simulation node's zoom-in: the cast's Agent nodes and the
  // Location (reusing any already on the canvas), and a Simulation node
  // set to the zoomed start time and length, all wired together, laid out
  // to the right of the City node. Residents promoted by the zoom aren't
  // in `data` yet, so they come in with the result (same trick as
  // placeAgentNode), then the city data is refreshed.
  const addZoomScene = useCallback(
    (cityNodeId: string, result: CityZoomResult) => {
      if (!data) return;
      const known = new Set(data.characters.map((c) => c.id));
      const augmented: HistoryData = { ...data, characters: [...data.characters, ...result.characters.filter((c) => !known.has(c.id))] };
      const simId = newNodeId('sim');
      const newEdges: Edge[] = [];
      setNodes((prev) => {
        const list = prev ?? [];
        const city = list.find((n) => n.id === cityNodeId);
        const x0 = (city?.position.x ?? 0) + (city?.measured?.width ?? city?.width ?? 340) + 120;
        const y0 = city?.position.y ?? 0;
        const added: Node[] = [];
        result.agent_ids.forEach((agentId, i) => {
          const existing = list.find((n) => n.type === 'agent' && (n.data as { character: Character }).character.id === agentId);
          let nodeId = existing?.id;
          if (!existing) {
            nodeId = `agent:${agentId}`;
            const built = toEntityRenderNode(
              { id: nodeId, type: 'agent', position: { x: x0, y: y0 + i * 190 }, data: { characterId: agentId } },
              augmented, onExpandAgent, onExpandPlace, onRemoveMissing,
            );
            if (built) added.push(built);
          }
          newEdges.push({ id: `e:${nodeId}->${simId}`, source: nodeId!, sourceHandle: 'agent:out', target: simId, targetHandle: 'agents:in' });
        });
        if (result.place_id) {
          const existing = list.find((n) => n.type === 'location' && (n.data as { place: { id: string } }).place.id === result.place_id);
          let nodeId = existing?.id;
          if (!existing) {
            nodeId = `place:${result.place_id}`;
            const built = toEntityRenderNode(
              { id: nodeId, type: 'location', position: { x: x0, y: y0 - 220 }, data: { placeId: result.place_id } },
              augmented, onExpandAgent, onExpandPlace, onRemoveMissing,
            );
            if (built) added.push(built);
          }
          newEdges.push({ id: `e:${nodeId}->${simId}`, source: nodeId!, sourceHandle: 'place:out', target: simId, targetHandle: 'place:in' });
        }
        added.push({
          id: simId,
          type: 'sim',
          position: { x: x0 + 320, y: y0 },
          data: {
            ticks: result.ticks,
            tickMinutes: result.tick_minutes,
            startTime: result.start_time,
            directive: result.directive ?? '',
            provider: 'ollama',
            chatModel: '',
            verbose: true,
            agentNames: [],
            onTicksChange: pipeline.onTicksChange,
            onTickMinutesChange: pipeline.onTickMinutesChange,
            onStartTimeChange: pipeline.onStartTimeChange,
            onDirectiveChange: pipeline.onDirectiveChange,
            onProviderChange: pipeline.onProviderChange,
            onChatModelChange: pipeline.onChatModelChange,
            onVerboseChange: pipeline.onVerboseChange,
          },
        });
        return [...list, ...added];
      });
      setEdges((prev) => [...prev, ...newEdges]);
      if (result.characters.length) onDataRefresh?.();
    },
    [data, setNodes, setEdges, pipeline, onExpandAgent, onExpandPlace, onRemoveMissing, onDataRefresh],
  );

  const { registerZoomHandler } = pipeline;
  useEffect(() => {
    registerZoomHandler(addZoomScene);
    return () => registerZoomHandler(null);
  }, [registerZoomHandler, addZoomScene]);

  return { addToCanvas, addPipelineNode, addStyleNode, addNewAgent, placeAgentNode, addScratchNode, PIPELINE_TYPES };
}
