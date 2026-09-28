// Cross-node data derivation for the Simulation -> Treatment -> Frame ->
// Video pipeline. Every derived field (agentNames, candidates,
// sourceImagePath) is recomputed fresh from the current nodes/edges on
// every render rather than chained through another node's own derived
// output -- reading raw source data directly means there's no dependency
// on which node happens to be processed first in a .map() pass.
import type { Edge, Node } from '@xyflow/react';
import { visuals } from '../api/client';
import type { GraphNode, HistoryData, Style } from '../api/types';
import type { AgentNodeData } from './nodes/AgentNode';
import type { FrameNodeData } from './nodes/FrameNode';
import type { ImageNodeData } from './nodes/ImageNode';
import type { LocationNodeData } from './nodes/LocationNode';
import type { SimulationNodeData } from './nodes/SimulationNode';
import type { StoryboardNodeData } from './nodes/StoryboardNode';
import type { StyleNodeData } from './nodes/StyleNode';
import type { TreatmentCandidate, TreatmentNodeData } from './nodes/TreatmentNode';
import type { VideoNodeData } from './nodes/VideoNode';

export interface PipelineCallbacks {
  onTicksChange: (nodeId: string, ticks: number) => void;
  onTickMinutesChange: (nodeId: string, tickMinutes: number) => void;
  onStartTimeChange: (nodeId: string, startTime: string) => void;
  onDirectiveChange: (nodeId: string, directive: string) => void;
  onProviderChange: (nodeId: string, provider: string) => void;
  onChatModelChange: (nodeId: string, chatModel: string) => void;
  onVerboseChange: (nodeId: string, verbose: boolean) => void;
  onSubjectChange: (nodeId: string, subjectId: string) => void;
  onTreatmentGenerated: (nodeId: string, text: string, shots: string[]) => void;
  onTreatmentProviderChange: (nodeId: string, provider: string) => void;
  onTreatmentModelChange: (nodeId: string, model: string) => void;
  onCreateStoryboard: (
    treatmentNodeId: string,
    shots: string[],
    agentIds: string[],
    placeIds: string[],
    styleIds: string[],
    agentNames: string[],
    placeNames: string[],
    styleNames: string[],
  ) => void;
  onExpandStoryboard: (storyboardId: string) => void;
  onFrameUpdate: (nodeId: string, patch: Partial<FrameNodeData>) => void;
  onVideoUpdate: (nodeId: string, patch: Partial<VideoNodeData>) => void;
  onStyleLoaded: (nodeId: string, style: Style) => void;
  onStyleUpdate: (nodeId: string, patch: Partial<Style>) => void;
  onStyleDelete: (nodeId: string) => void;
}

export function toPipelineRenderNode(gn: GraphNode, cb: PipelineCallbacks): Node | null {
  if (gn.type === 'sim') {
    return {
      id: gn.id,
      type: 'sim',
      position: gn.position,
      width: gn.width,
      height: gn.height,
      data: {
        ticks: (gn.data.ticks as number) ?? 8,
        tickMinutes: (gn.data.tickMinutes as number) ?? 30,
        startTime: (gn.data.startTime as string) ?? '06:00',
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
        onTickMinutesChange: cb.onTickMinutesChange,
        onStartTimeChange: cb.onStartTimeChange,
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
        onCreateStoryboard: cb.onCreateStoryboard,
        onProviderChange: cb.onTreatmentProviderChange,
        onModelChange: cb.onTreatmentModelChange,
      },
    };
  }
  if (gn.type === 'frame') {
    return {
      id: gn.id,
      type: 'frame',
      position: gn.position,
      // Falls back to the same 540x430 floor NodeShell already enforces
      // as a resize minimum (see FrameNode.tsx's minWidth/minHeight) --
      // without an explicit size here, React Flow leaves the node
      // wrapper unsized until the user's first manual resize, so every
      // never-touched Frame shrink-to-fits its own content independently
      // and ends up a different size from its neighbors (the "why are
      // these all different sizes" bug a freshly-seeded Storyboard hits
      // immediately, before anyone's dragged a single handle).
      width: gn.width ?? 540,
      // 480, not the 430 floor: room for the edit-prompt row and the
      // input-image line an image-bearing Frame can show.
      height: gn.height ?? 480,
      data: {
        shotIndex: gn.data.shotIndex as number,
        prompt: (gn.data.prompt as string) ?? '',
        editPrompt: (gn.data.editPrompt as string) ?? '',
        url: gn.data.url as string | undefined,
        localPath: gn.data.localPath as string | undefined,
        onUpdate: cb.onFrameUpdate,
      },
    };
  }
  if (gn.type === 'video') {
    return {
      id: gn.id,
      type: 'video',
      position: gn.position,
      width: gn.width ?? 540,
      height: gn.height ?? 430,
      data: {
        prompt: (gn.data.prompt as string) ?? '',
        url: gn.data.url as string | undefined,
        localPath: gn.data.localPath as string | undefined,
        onUpdate: cb.onVideoUpdate,
      },
    };
  }
  if (gn.type === 'style') {
    return {
      id: gn.id,
      type: 'style',
      position: gn.position,
      // A fixed width floor, unlike height (left to grow naturally with
      // content) -- without this, a never-resized Style node shrink-to-
      // fits its own content, and .style-ref-grid's `auto-fill` columns
      // compute their "natural" width as if every reference-image
      // thumbnail sat in one unbroken row (a CSS grid quirk: auto-fill
      // inside a shrink-to-fit ancestor doesn't wrap), ballooning the
      // whole node wider with every reference image added. A fixed width
      // gives the grid something real to wrap columns within.
      width: gn.width ?? 340,
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
  if (gn.type === 'storyboard') {
    return {
      id: gn.id,
      type: 'storyboard',
      position: gn.position,
      // Same fixed-width-floor fix as Style just above, and for the same
      // reason -- this node can render a thumbnail grid of its own
      // generated Frame images (StoryboardNode.tsx), which would balloon
      // the node under shrink-to-fit exactly like Style's reference-image
      // grid did.
      width: gn.width ?? 340,
      height: gn.height,
      data: {
        shotCount: (gn.data.shotCount as number) ?? 0,
        contextAgentNames: (gn.data.contextAgentNames as string[]) ?? [],
        contextPlaceNames: (gn.data.contextPlaceNames as string[]) ?? [],
        contextStyleNames: (gn.data.contextStyleNames as string[]) ?? [],
        onExpand: cb.onExpandStoryboard,
      },
    };
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
      data: { ticks: d.ticks, tickMinutes: d.tickMinutes, startTime: d.startTime, directive: d.directive, provider: d.provider, chatModel: d.chatModel, verbose: d.verbose },
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
    return {
      id: n.id,
      type: 'frame',
      position: n.position,
      width: n.width,
      height: n.height,
      data: { shotIndex: d.shotIndex, prompt: d.prompt, editPrompt: d.editPrompt, url: d.url, localPath: d.localPath },
    };
  }
  if (n.type === 'video') {
    const d = n.data as VideoNodeData;
    return { id: n.id, type: 'video', position: n.position, width: n.width, height: n.height, data: { prompt: d.prompt, url: d.url, localPath: d.localPath } };
  }
  if (n.type === 'style') {
    const d = n.data as StyleNodeData;
    return { id: n.id, type: 'style', position: n.position, width: n.width, height: n.height, data: { styleId: d.styleId } };
  }
  if (n.type === 'text-viewer') {
    return { id: n.id, type: 'text-viewer', position: n.position, width: n.width, height: n.height, data: {} };
  }
  if (n.type === 'storyboard') {
    const d = n.data as StoryboardNodeData;
    return {
      id: n.id,
      type: 'storyboard',
      position: n.position,
      width: n.width,
      height: n.height,
      data: { shotCount: d.shotCount, contextAgentNames: d.contextAgentNames, contextPlaceNames: d.contextPlaceNames, contextStyleNames: d.contextStyleNames },
    };
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
// Frame's image:in port -- the actual files of whatever image-producing
// nodes are wired in (another Frame, a scratch Image, or an entity-attached
// Image, whose file lives in that entity's media record). Order follows
// edge order; a node wired to itself, or one with nothing generated yet,
// contributes nothing.
function connectedInputImagePaths(nodeId: string, edges: Edge[], byId: Map<string, Node>, historyData: HistoryData): string[] {
  const paths: string[] = [];
  for (const e of edges) {
    if (e.target !== nodeId || e.targetHandle !== 'image:in' || e.source === nodeId) continue;
    const source = byId.get(e.source);
    let path: string | undefined;
    if (source?.type === 'frame' || source?.type === 'scratch-image') {
      path = (source.data as { localPath?: string }).localPath;
    } else if (source?.type === 'image') {
      const d = source.data as ImageNodeData;
      path = d.mediaId ? historyData.media[d.entityId]?.find((m) => m.id === d.mediaId)?.local_path : undefined;
    }
    if (path) paths.push(path);
  }
  return paths;
}

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

function connectedPlaces(nodeId: string, handle: string, edges: Edge[], byId: Map<string, Node>): { id: string; name: string }[] {
  return edges
    .filter((e) => e.target === nodeId && e.targetHandle === handle)
    .map((e) => byId.get(e.source))
    .filter((n): n is Node => Boolean(n && n.type === 'location'))
    .map((n) => {
      const p = (n.data as LocationNodeData).place;
      return { id: p.id, name: p.name };
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
      // Extra cast/setting context from the Treatment's own agent:in/
      // place:in ports -- independent of `candidates` (who the run:in
      // transcript says was involved) or `run:in` itself; a character or
      // place explicitly wired in here still gets described even if they
      // never appear in the recorded run at all (see agents/routes.py's
      // POST /treatment docstring).
      const contextAgents = connectedAgents(n.id, 'agent:in', edges, byId);
      const contextPlaces = connectedPlaces(n.id, 'place:in', edges, byId);
      // Doesn't feed generation at all (unlike agent/place, which build
      // the CAST:/SETTING: prompt blocks) -- resolved purely so "create
      // storyboard" can carry it through to the seeded Frame nodes' own
      // style:in ports, same as agent/place.
      const contextStyles = connectedStyles(n.id, edges, byId);
      return {
        ...n,
        data: {
          ...n.data,
          candidates,
          agentIds: contextAgents.map((a) => a.id),
          placeIds: contextPlaces.map((p) => p.id),
          styleIds: contextStyles.map((s) => s.id),
          contextAgentNames: contextAgents.map((a) => a.name),
          contextPlaceNames: contextPlaces.map((p) => p.name),
          contextStyleNames: contextStyles.map((s) => s.name),
          hasAgentRef: hasEdge(n.id, 'agent:in', edges),
          hasPlaceRef: hasEdge(n.id, 'place:in', edges),
          hasStyleRef: hasEdge(n.id, 'style:in', edges),
        },
      };
    }

    if (n.type === 'video') {
      const imgEdge = edges.find((e) => e.target === n.id && e.targetHandle === 'image:in');
      const source = imgEdge && byId.get(imgEdge.source);
      let sourceImagePath: string | undefined;
      let sourceImageUrl: string | undefined;
      if (source?.type === 'frame') {
        const d = source.data as FrameNodeData;
        sourceImagePath = d.localPath;
        sourceImageUrl = d.url ? visuals.fileUrl(d.url) : undefined;
      }
      const merged = mergeStyles(connectedStyles(n.id, edges, byId));
      return {
        ...n,
        data: { ...n.data, sourceImagePath, sourceImageUrl, mergedStylePrompt: merged.stylePrompt, hasStyleRef: hasEdge(n.id, 'style:in', edges) },
      };
    }

    if (n.type === 'frame') {
      const merged = mergeStyles(connectedStyles(n.id, edges, byId));
      const entityRefs = connectedEntityReferenceImages(n.id, edges, byId, historyData);
      return {
        ...n,
        data: {
          ...n.data,
          mergedStylePrompt: merged.stylePrompt,
          mergedStyleReferenceImages: merged.styleReferenceImages,
          mergedEntityReferenceImages: entityRefs,
          inputImagePaths: connectedInputImagePaths(n.id, edges, byId, historyData),
          hasAgentRef: hasEdge(n.id, 'agent:in', edges),
          hasPlaceRef: hasEdge(n.id, 'place:in', edges),
          hasStyleRef: hasEdge(n.id, 'style:in', edges),
          hasImageRef: hasEdge(n.id, 'image:in', edges),
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
          hasStyleRef: hasEdge(n.id, 'style:in', edges),
        },
      };
    }
    if (n.type === 'scratch-image') {
      const merged = mergeStyles(connectedStyles(n.id, edges, byId));
      return {
        ...n,
        data: { ...n.data, mergedStylePrompt: merged.stylePrompt, mergedStyleReferenceImages: merged.styleReferenceImages, hasStyleRef: hasEdge(n.id, 'style:in', edges) },
      };
    }

    if (n.type === 'text-viewer') {
      const textEdge = edges.find((e) => e.target === n.id && e.targetHandle === 'text:in');
      const source = textEdge && byId.get(textEdge.source);
      const text = source?.type === 'treatment' ? (source.data as TreatmentNodeData).text : undefined;
      return { ...n, data: { ...n.data, text } };
    }

    // Only drives the port fill/hollow styling here -- the seeded content
    // itself is a one-time snapshot baked in at creation (see
    // usePipelineCallbacks.ts's onCreateStoryboard), not kept live.
    if (n.type === 'storyboard') {
      return {
        ...n,
        data: {
          ...n.data,
          hasAgentRef: hasEdge(n.id, 'agent:in', edges),
          hasPlaceRef: hasEdge(n.id, 'place:in', edges),
          hasStyleRef: hasEdge(n.id, 'style:in', edges),
        },
      };
    }

    return n;
  });
}
