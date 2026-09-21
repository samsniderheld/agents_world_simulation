// Cross-node data derivation for the Simulation -> Treatment -> Frame ->
// Video pipeline. Every derived field (agentNames, candidates,
// sourceImagePath) is recomputed fresh from the current nodes/edges on
// every render rather than chained through another node's own derived
// output -- reading raw source data directly means there's no dependency
// on which node happens to be processed first in a .map() pass.
import type { Edge, Node } from '@xyflow/react';
import { city } from '../api/client';
import type { GraphNode, HistoryData, Style } from '../api/types';
import type { AgentNodeData } from './nodes/AgentNode';
import type { FrameNodeData } from './nodes/FrameNode';
import type { LocationNodeData } from './nodes/LocationNode';
import type { SimulationNodeData } from './nodes/SimulationNode';
import type { StyleNodeData } from './nodes/StyleNode';
import type { TreatmentCandidate, TreatmentNodeData } from './nodes/TreatmentNode';
import type { VideoNodeData } from './nodes/VideoNode';

export interface PipelineCallbacks {
  onTicksChange: (nodeId: string, ticks: number) => void;
  onDirectiveChange: (nodeId: string, directive: string) => void;
  onProviderChange: (nodeId: string, provider: string) => void;
  onChatModelChange: (nodeId: string, chatModel: string) => void;
  onVerboseChange: (nodeId: string, verbose: boolean) => void;
  onSubjectChange: (nodeId: string, subjectId: string) => void;
  onTreatmentGenerated: (nodeId: string, text: string, shots: string[]) => void;
  onTreatmentProviderChange: (nodeId: string, provider: string) => void;
  onTreatmentModelChange: (nodeId: string, model: string) => void;
  onEmitFrames: (nodeId: string, shots: string[]) => void;
  onFrameUpdate: (nodeId: string, patch: Partial<FrameNodeData>) => void;
  onVideoUpdate: (nodeId: string, patch: Partial<VideoNodeData>) => void;
  onStyleLoaded: (nodeId: string, style: Style) => void;
  onStyleUpdate: (nodeId: string, patch: Partial<Style>) => void;
  onStyleDelete: (nodeId: string) => void;
}

export function toPipelineRenderNode(gn: GraphNode, data: HistoryData, cb: PipelineCallbacks): Node | null {
  if (gn.type === 'sim') {
    return {
      id: gn.id,
      type: 'sim',
      position: gn.position,
      width: gn.width,
      height: gn.height,
      data: {
        ticks: (gn.data.ticks as number) ?? 8,
        directive: (gn.data.directive as string) ?? '',
        provider: (gn.data.provider as string) ?? 'ollama',
        chatModel: (gn.data.chatModel as string) ?? '',
        // Purely a display filter for this node's own log (see
        // enrichPipelineNodes/SimulationNode.tsx) -- unrelated to
        // simulation.run()'s own `verbose` param, which only controls
        // server-terminal printing and is never sent by this node.
        verbose: (gn.data.verbose as boolean) ?? true,
        agentNames: [],
        onTicksChange: cb.onTicksChange,
        onDirectiveChange: cb.onDirectiveChange,
        onProviderChange: cb.onProviderChange,
        onChatModelChange: cb.onChatModelChange,
        onVerboseChange: cb.onVerboseChange,
      },
    };
  }
  if (gn.type === 'treatment') {
    return {
      id: gn.id,
      type: 'treatment',
      position: gn.position,
      width: gn.width,
      height: gn.height,
      data: {
        subjectId: gn.data.subjectId as string | undefined,
        text: gn.data.text as string | undefined,
        shots: gn.data.shots as string[] | undefined,
        // Independent of whatever provider/model actually ran the
        // simulation -- agents/routes.py's POST /treatment already
        // accepts its own provider/model overrides (see
        // agents/treatment.generate_treatment), the frontend just never
        // exposed them before.
        provider: (gn.data.provider as string) ?? '',
        model: (gn.data.model as string) ?? '',
        candidates: [],
        onSubjectChange: cb.onSubjectChange,
        onGenerated: cb.onTreatmentGenerated,
        onEmitFrames: cb.onEmitFrames,
        onProviderChange: cb.onTreatmentProviderChange,
        onModelChange: cb.onTreatmentModelChange,
      },
    };
  }
  if (gn.type === 'frame') {
    const entityId = gn.data.entityId as string | undefined;
    const mediaId = gn.data.mediaId as string | undefined;
    const media = mediaId && entityId ? data.media[entityId]?.find((m) => m.id === mediaId) : undefined;
    return {
      id: gn.id,
      type: 'frame',
      position: gn.position,
      width: gn.width,
      height: gn.height,
      data: {
        entityId,
        shotIndex: gn.data.shotIndex as number,
        prompt: (gn.data.prompt as string) ?? '',
        mediaId,
        mediaUrl: media ? city.fileUrl(media.url) : undefined,
        localPath: media?.local_path,
        onUpdate: cb.onFrameUpdate,
      },
    };
  }
  if (gn.type === 'video') {
    // entityId isn't persisted for video nodes -- it's derived below in
    // enrichPipelineNodes() from whichever Frame is connected, since a
    // Video node has no entity of its own. Media resolution therefore
    // also happens there, not here (this function has no edges to look
    // the connection up with).
    return {
      id: gn.id,
      type: 'video',
      position: gn.position,
      width: gn.width,
      height: gn.height,
      data: { prompt: (gn.data.prompt as string) ?? '', mediaId: gn.data.mediaId as string | undefined, onUpdate: cb.onVideoUpdate },
    };
  }
  if (gn.type === 'style') {
    return {
      id: gn.id,
      type: 'style',
      position: gn.position,
      width: gn.width,
      height: gn.height,
      data: { styleId: gn.data.styleId as string, onLoaded: cb.onStyleLoaded, onUpdate: cb.onStyleUpdate, onDelete: cb.onStyleDelete },
    };
  }
  if (gn.type === 'text-viewer') {
    // No persisted data of its own -- `text` is entirely derived below in
    // enrichPipelineNodes() from whatever's connected to text:in, the
    // same way Video's sourceImagePath has no state here either.
    return { id: gn.id, type: 'text-viewer', position: gn.position, width: gn.width, height: gn.height, data: {} };
  }
  return null;
}

export function pipelineToGraphNode(n: Node): GraphNode | null {
  if (n.type === 'sim') {
    const d = n.data as SimulationNodeData;
    return {
      id: n.id,
      type: 'sim',
      position: n.position,
      width: n.width,
      height: n.height,
      data: { ticks: d.ticks, directive: d.directive, provider: d.provider, chatModel: d.chatModel, verbose: d.verbose },
    };
  }
  if (n.type === 'treatment') {
    const d = n.data as TreatmentNodeData;
    return {
      id: n.id,
      type: 'treatment',
      position: n.position,
      width: n.width,
      height: n.height,
      data: { subjectId: d.subjectId, text: d.text, shots: d.shots, provider: d.provider, model: d.model },
    };
  }
  if (n.type === 'frame') {
    const d = n.data as FrameNodeData;
    return { id: n.id, type: 'frame', position: n.position, width: n.width, height: n.height, data: { entityId: d.entityId, shotIndex: d.shotIndex, prompt: d.prompt, mediaId: d.mediaId } };
  }
  if (n.type === 'video') {
    const d = n.data as VideoNodeData;
    return { id: n.id, type: 'video', position: n.position, width: n.width, height: n.height, data: { prompt: d.prompt, mediaId: d.mediaId } };
  }
  if (n.type === 'style') {
    const d = n.data as StyleNodeData;
    return { id: n.id, type: 'style', position: n.position, width: n.width, height: n.height, data: { styleId: d.styleId } };
  }
  if (n.type === 'text-viewer') {
    return { id: n.id, type: 'text-viewer', position: n.position, width: n.width, height: n.height, data: {} };
  }
  return null;
}

function connectedStyles(nodeId: string, edges: Edge[], byId: Map<string, Node>): Style[] {
  return edges
    .filter((e) => e.target === nodeId && e.targetHandle === 'style:in')
    .map((e) => byId.get(e.source))
    .filter((n): n is Node => Boolean(n && n.type === 'style'))
    .map((n) => (n.data as StyleNodeData).style)
    .filter((s): s is Style => Boolean(s));
}

// "Prompts joined with ', ' and reference arrays concatenated" -- per the
// design spec's merge rule; order follows edge-creation order (the order
// `edges` already holds them in), not any sorting of our own.
function mergeStyles(styles: Style[]): { stylePrompt?: string; styleReferenceImages?: string[] } {
  if (styles.length === 0) return {};
  return {
    stylePrompt: styles.map((s) => s.style_prompt).filter(Boolean).join(', ') || undefined,
    styleReferenceImages: styles.flatMap((s) => s.reference_images),
  };
}

// Image/Frame's agent:in/place:in ports -- unlike Simulation's agents:in/
// place:in (which pick *who runs* or *where*), these feed the connected
// entity's own previously-generated images in as reference images, the
// same slot a Style's reference_images fill (see visuals/routes.py's
// _style_reference_images(), which merges both into one image_paths list
// server-side either way).
function connectedEntityReferenceImages(nodeId: string, edges: Edge[], byId: Map<string, Node>, historyData: HistoryData): string[] {
  const paths: string[] = [];
  for (const e of edges) {
    if (e.target !== nodeId) continue;
    if (e.targetHandle !== 'agent:in' && e.targetHandle !== 'place:in') continue;
    const source = byId.get(e.source);
    let entityId: string | undefined;
    if (source?.type === 'agent') entityId = (source.data as AgentNodeData).character.id;
    else if (source?.type === 'location') entityId = (source.data as LocationNodeData).place.id;
    if (!entityId) continue;
    for (const m of historyData.media[entityId] ?? []) {
      if (m.kind === 'image' && m.local_path) paths.push(m.local_path);
    }
  }
  return paths;
}

// Whether a given port actually has something plugged in -- independent
// of connectedEntityReferenceImages's result, since a connected Agent/
// Location with zero existing photos yet should still show its port as
// "live," not fall back to looking exactly like nothing's wired at all.
function hasEdge(nodeId: string, handle: string, edges: Edge[]): boolean {
  return edges.some((e) => e.target === nodeId && e.targetHandle === handle);
}

function connectedAgents(nodeId: string, handle: string, edges: Edge[], byId: Map<string, Node>): { id: string; name: string }[] {
  return edges
    .filter((e) => e.target === nodeId && e.targetHandle === handle)
    .map((e) => byId.get(e.source))
    .filter((n): n is Node => Boolean(n && n.type === 'agent'))
    .map((n) => {
      const c = (n.data as AgentNodeData).character;
      return { id: c.id, name: c.name };
    });
}

export function enrichPipelineNodes(nodes: Node[], edges: Edge[], historyData: HistoryData): Node[] {
  const byId = new Map(nodes.map((n) => [n.id, n]));

  return nodes.map((n) => {
    if (n.type === 'sim') {
      const agentNames = connectedAgents(n.id, 'agents:in', edges, byId).map((a) => a.name);
      const placeEdge = edges.find((e) => e.target === n.id && e.targetHandle === 'place:in');
      const placeSource = placeEdge && byId.get(placeEdge.source);
      const place = placeSource?.type === 'location' ? (placeSource.data as LocationNodeData).place : undefined;
      return { ...n, data: { ...n.data, agentNames, placeId: place?.id, placeName: place?.name } };
    }

    if (n.type === 'treatment') {
      const runEdge = edges.find((e) => e.target === n.id && e.targetHandle === 'run:in');
      const source = runEdge && byId.get(runEdge.source);
      let candidates: TreatmentCandidate[] = [];
      if (source?.type === 'agent') {
        const c = (source.data as AgentNodeData).character;
        candidates = [{ id: c.id, name: c.name }];
      } else if (source?.type === 'sim') {
        candidates = connectedAgents(source.id, 'agents:in', edges, byId);
      }
      return { ...n, data: { ...n.data, candidates } };
    }

    if (n.type === 'video') {
      const imgEdge = edges.find((e) => e.target === n.id && e.targetHandle === 'image:in');
      const source = imgEdge && byId.get(imgEdge.source);
      let sourceImagePath: string | undefined;
      let sourceImageUrl: string | undefined;
      let entityId: string | undefined;
      if (source?.type === 'frame') {
        const d = source.data as FrameNodeData;
        sourceImagePath = d.localPath;
        sourceImageUrl = d.mediaUrl;
        entityId = d.entityId;
      }
      // The video's own generated media (once it has a mediaId) also
      // needs the entity to look it up under -- only known now, from the
      // connected Frame above, hence resolved here rather than in
      // toPipelineRenderNode (which has no edges to trace the connection
      // with).
      const existingMediaId = (n.data as VideoNodeData).mediaId;
      const existingMedia = entityId && existingMediaId ? historyData.media[entityId]?.find((m) => m.id === existingMediaId) : undefined;
      const merged = mergeStyles(connectedStyles(n.id, edges, byId));
      return {
        ...n,
        data: {
          ...n.data,
          entityId,
          sourceImagePath,
          sourceImageUrl,
          mediaUrl: existingMedia ? city.fileUrl(existingMedia.url) : (n.data as VideoNodeData).mediaUrl,
          mergedStylePrompt: merged.stylePrompt,
        },
      };
    }

    if (n.type === 'frame') {
      const merged = mergeStyles(connectedStyles(n.id, edges, byId));
      // A Frame from "emit frames" already has entityId baked in at
      // creation. One dropped manually (per the requirement that every
      // node type be placeable anywhere, not just spawned by another
      // node) starts without one -- if it's wired to a Treatment's
      // shots:out, borrow that treatment's chosen subject rather than
      // leaving the Frame permanently non-functional.
      let entityId = (n.data as FrameNodeData).entityId;
      if (!entityId) {
        const shotEdge = edges.find((e) => e.target === n.id && e.targetHandle === 'shot:in');
        const source = shotEdge && byId.get(shotEdge.source);
        if (source?.type === 'treatment') entityId = (source.data as TreatmentNodeData).subjectId;
      }
      const entityRefs = connectedEntityReferenceImages(n.id, edges, byId, historyData);
      return {
        ...n,
        data: {
          ...n.data,
          entityId,
          mergedStylePrompt: merged.stylePrompt,
          mergedStyleReferenceImages: merged.styleReferenceImages,
          mergedEntityReferenceImages: entityRefs,
          hasAgentRef: hasEdge(n.id, 'agent:in', edges),
          hasPlaceRef: hasEdge(n.id, 'place:in', edges),
        },
      };
    }

    // ImageNode (entity-attached) additionally takes agent:in/place:in
    // reference connections; ScratchImageNode has no such ports (a
    // scratch board's freeform image has nothing of its own to attach
    // agent/location context to), so it only gets the style merge.
    if (n.type === 'image') {
      const merged = mergeStyles(connectedStyles(n.id, edges, byId));
      const entityRefs = connectedEntityReferenceImages(n.id, edges, byId, historyData);
      return {
        ...n,
        data: {
          ...n.data,
          mergedStylePrompt: merged.stylePrompt,
          mergedStyleReferenceImages: merged.styleReferenceImages,
          mergedEntityReferenceImages: entityRefs,
          hasAgentRef: hasEdge(n.id, 'agent:in', edges),
          hasPlaceRef: hasEdge(n.id, 'place:in', edges),
        },
      };
    }
    if (n.type === 'scratch-image') {
      const merged = mergeStyles(connectedStyles(n.id, edges, byId));
      return { ...n, data: { ...n.data, mergedStylePrompt: merged.stylePrompt, mergedStyleReferenceImages: merged.styleReferenceImages } };
    }

    if (n.type === 'text-viewer') {
      const textEdge = edges.find((e) => e.target === n.id && e.targetHandle === 'text:in');
      const source = textEdge && byId.get(textEdge.source);
      const text = source?.type === 'treatment' ? (source.data as TreatmentNodeData).text : undefined;
      return { ...n, data: { ...n.data, text } };
    }

    return n;
  });
}
