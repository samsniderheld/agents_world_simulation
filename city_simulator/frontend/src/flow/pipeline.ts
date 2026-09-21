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
  onSubjectChange: (nodeId: string, subjectId: string) => void;
  onTreatmentGenerated: (nodeId: string, text: string, shots: string[]) => void;
  onEmitFrames: (nodeId: string, shots: string[]) => void;
  onFrameUpdate: (nodeId: string, patch: Partial<FrameNodeData>) => void;
  onVideoUpdate: (nodeId: string, patch: Partial<VideoNodeData>) => void;
  onStyleLoaded: (nodeId: string, style: Style) => void;
  onStyleUpdate: (nodeId: string, patch: Partial<Style>) => void;
}

export function toPipelineRenderNode(gn: GraphNode, data: HistoryData, cb: PipelineCallbacks): Node | null {
  if (gn.type === 'sim') {
    return {
      id: gn.id,
      type: 'sim',
      position: gn.position,
      data: { ticks: (gn.data.ticks as number) ?? 8, agentNames: [], onTicksChange: cb.onTicksChange },
    };
  }
  if (gn.type === 'treatment') {
    return {
      id: gn.id,
      type: 'treatment',
      position: gn.position,
      data: {
        subjectId: gn.data.subjectId as string | undefined,
        text: gn.data.text as string | undefined,
        shots: gn.data.shots as string[] | undefined,
        candidates: [],
        onSubjectChange: cb.onSubjectChange,
        onGenerated: cb.onTreatmentGenerated,
        onEmitFrames: cb.onEmitFrames,
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
      data: { prompt: (gn.data.prompt as string) ?? '', mediaId: gn.data.mediaId as string | undefined, onUpdate: cb.onVideoUpdate },
    };
  }
  if (gn.type === 'style') {
    return { id: gn.id, type: 'style', position: gn.position, data: { styleId: gn.data.styleId as string, onLoaded: cb.onStyleLoaded, onUpdate: cb.onStyleUpdate } };
  }
  return null;
}

export function pipelineToGraphNode(n: Node): GraphNode | null {
  if (n.type === 'sim') {
    const d = n.data as SimulationNodeData;
    return { id: n.id, type: 'sim', position: n.position, data: { ticks: d.ticks } };
  }
  if (n.type === 'treatment') {
    const d = n.data as TreatmentNodeData;
    return { id: n.id, type: 'treatment', position: n.position, data: { subjectId: d.subjectId, text: d.text, shots: d.shots } };
  }
  if (n.type === 'frame') {
    const d = n.data as FrameNodeData;
    return { id: n.id, type: 'frame', position: n.position, data: { entityId: d.entityId, shotIndex: d.shotIndex, prompt: d.prompt, mediaId: d.mediaId } };
  }
  if (n.type === 'video') {
    const d = n.data as VideoNodeData;
    return { id: n.id, type: 'video', position: n.position, data: { prompt: d.prompt, mediaId: d.mediaId } };
  }
  if (n.type === 'style') {
    const d = n.data as StyleNodeData;
    return { id: n.id, type: 'style', position: n.position, data: { styleId: d.styleId } };
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
      return { ...n, data: { ...n.data, entityId, mergedStylePrompt: merged.stylePrompt, mergedStyleReferenceImages: merged.styleReferenceImages } };
    }

    // ImageNode (entity-attached) and ScratchImageNode (ungrounded) both
    // take a style:in connection the exact same way Frame does -- merged
    // here so both actually thread it into their generate call, not just
    // render a port that looks connected.
    if (n.type === 'image' || n.type === 'scratch-image') {
      const merged = mergeStyles(connectedStyles(n.id, edges, byId));
      return { ...n, data: { ...n.data, mergedStylePrompt: merged.stylePrompt, mergedStyleReferenceImages: merged.styleReferenceImages } };
    }

    return n;
  });
}
