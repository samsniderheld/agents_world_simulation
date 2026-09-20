// Thin typed wrappers over the existing Flask JSON API -- one function per
// route, request/response shapes verified against the real route handlers
// (history/routes.py, agents/routes.py, visuals/routes.py,
// citystate/routes.py), not guessed. No endpoint here is new; Phase 4/5
// of the plan will add the ones that don't exist yet (graph persistence,
// styles, multi-city).

import type {
  AgentRecord,
  AgentsState,
  Character,
  CitySummary,
  GraphDoc,
  HistoryData,
  JobStatus,
  MediaItem,
  Style,
  Treatment,
  VisualsResult,
} from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const message = (body && (body.error as string)) || `${res.status} ${res.statusText}`;
    throw new Error(message);
  }
  return body as T;
}

const json = (body: unknown) => JSON.stringify(body);

// ---- history (/api/history) ------------------------------------------

export const history = {
  status: () => request<JobStatus>('/api/history/status'),

  data: () => request<HistoryData>('/api/history/data'),

  deleteCity: () =>
    request<{ ok: boolean; error: string | null }>('/api/history/data', { method: 'DELETE' }),

  log: (since = 0) => request<{ lines: string[]; next: number }>(`/api/history/log?since=${since}`),

  // Without cityId: always creates a brand new city, no confirmation
  // needed. With cityId (regenerating an existing one in place): a 409
  // with needs_confirmation: true comes back first -- callers pass
  // confirmOverwrite: true once the user has confirmed (see
  // history/routes.py's generate()).
  generate: (params: {
    cityId?: string;
    seed?: number;
    figuresPerEra?: number;
    eventsPerFigure?: number;
    noLlm?: boolean;
    confirmOverwrite?: boolean;
  }) =>
    request<{ ok: boolean; error: string | null; needs_confirmation?: boolean }>(
      '/api/history/generate',
      {
        method: 'POST',
        body: json({
          city_id: params.cityId,
          seed: params.seed,
          figures_per_era: params.figuresPerEra,
          events_per_figure: params.eventsPerFigure,
          no_llm: params.noLlm ?? false,
          confirm_overwrite: params.confirmOverwrite ?? false,
        }),
      },
    ),

  listCities: () => request<{ cities: CitySummary[] }>('/api/history/cities'),

  activateCity: (cityId: string) => request<{ ok: boolean; city: HistoryData }>(`/api/history/cities/${cityId}/activate`, { method: 'POST' }),

  deleteCityById: (cityId: string) => request<{ ok: boolean; error: string | null }>(`/api/history/cities/${cityId}`, { method: 'DELETE' }),

  previewCharacter: (params: { placeId?: string; occupation?: string; sex?: string }) =>
    request<{ character: Character }>('/api/history/characters/preview', {
      method: 'POST',
      body: json({ place_id: params.placeId, occupation: params.occupation, sex: params.sex }),
    }),

  createCharacter: (character: Character) =>
    request<{ character: Character }>('/api/history/characters', {
      method: 'POST',
      body: json({ character }),
    }),
};

// ---- agents (/api/agents) ----------------------------------------------

// The agents package has no id of its own -- POST /run selects by plain
// display name (agent_names: string[]). This resolver is the one place
// that translates a stable char_* id (what nodes hold) into the name the
// backend actually expects, by name-matching HistoryData.characters.
export function resolveAgentNames(data: HistoryData, ids: string[]): string[] {
  const byId = new Map<string, string>(data.characters.map((c) => [c.id, c.name]));
  return ids.map((id) => {
    const name = byId.get(id);
    if (!name) throw new Error(`no character with id ${id} in the active city`);
    return name;
  });
}

export const agentsApi = {
  roster: () =>
    request<{ roster: Array<{ name: string; age: number; traits: string; currently: string; location: string }> }>(
      '/api/agents/roster',
    ),

  providers: () => request<{ providers: string[] }>('/api/agents/providers'),

  models: (provider?: string) =>
    request<{ models: string[]; error?: string }>(
      `/api/agents/models${provider ? `?provider=${encodeURIComponent(provider)}` : ''}`,
    ),

  state: () => request<AgentsState>('/api/agents/state'),

  events: (since = 0) =>
    request<{ events: unknown[]; next: number }>(`/api/agents/events?since=${since}`),

  run: (params: {
    agentNames: string[];
    ticks?: number;
    provider?: string;
    tickSleep?: number;
    chatModel?: string;
    embedModel?: string;
    contextTokens?: number;
    verbose?: boolean;
    // A Location -> Simulation edge: convenes every selected agent at
    // placeId for this run only (see agents/routes.py's run() docstring).
    placeId?: string;
    locationMode?: 'grounded' | 'convene';
  }) =>
    request<{ ok: boolean; error: string | null }>('/api/agents/run', {
      method: 'POST',
      body: json({
        agent_names: params.agentNames,
        ticks: params.ticks ?? 8,
        provider: params.provider,
        tick_sleep: params.tickSleep ?? 0,
        chat_model: params.chatModel,
        embed_model: params.embedModel,
        context_tokens: params.contextTokens,
        verbose: params.verbose ?? false,
        place_id: params.placeId,
        location_mode: params.locationMode ?? 'grounded',
      }),
    }),

  stop: () => request<{ ok: boolean }>('/api/agents/stop', { method: 'POST' }),

  generateTreatment: (agentId: string) =>
    request<{ treatment: Treatment }>('/api/agents/treatment', {
      method: 'POST',
      body: json({ agent_id: agentId }),
    }),

  treatmentShots: (text: string) =>
    request<{ shots: string[] }>(`/api/agents/treatment/shots?text=${encodeURIComponent(text)}`),
};

// ---- visuals (/api/visuals) ---------------------------------------------

export const visuals = {
  // A generated result's `url` is relative to visuals/data/ (see
  // storage.py's relative_path docstring) -- servable via this route.
  // Scratch nodes use this directly since they have no citystate entity
  // to relocate the file into (see city.fileUrl for that other case).
  fileUrl: (url: string) => `/api/visuals/files/${url}`,

  providers: () => request<{ available: string[]; current: string }>('/api/visuals/providers'),

  setProvider: (provider: string) =>
    request<{ ok: boolean; provider?: string; error?: string }>('/api/visuals/provider', {
      method: 'POST',
      body: json({ provider }),
    }),

  status: () => request<JobStatus>('/api/visuals/status'),

  result: () => request<VisualsResult>('/api/visuals/result'),

  upload: async (file: File) => {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/visuals/upload', { method: 'POST', body: form });
    const body = await res.json();
    if (!res.ok || !body.ok) throw new Error(body.error || 'upload failed');
    return body as { ok: true; path: string; url: string };
  },

  generateImage: (params: {
    prompt: string;
    imagePaths?: string[];
    stylePrompt?: string;
    styleReferenceImages?: string[];
    options?: Record<string, unknown>;
  }) =>
    request<{ ok: boolean; error: string | null }>('/api/visuals/generate-image', {
      method: 'POST',
      body: json({
        prompt: params.prompt,
        image_paths: params.imagePaths ?? null,
        style_prompt: params.stylePrompt,
        style_reference_images: params.styleReferenceImages,
        options: params.options ?? {},
      }),
    }),

  // generate-video always needs a source image today -- there's no
  // text-to-video path in providers/base.py, so imagePath is required
  // here rather than optional.
  generateVideo: (params: { prompt: string; imagePath: string; stylePrompt?: string; options?: Record<string, unknown> }) =>
    request<{ ok: boolean; error: string | null }>('/api/visuals/generate-video', {
      method: 'POST',
      body: json({ prompt: params.prompt, image_path: params.imagePath, style_prompt: params.stylePrompt, options: params.options ?? {} }),
    }),

  generateVideoFromReference: (params: {
    prompt: string;
    videoPath?: string;
    imagePaths?: string[];
    options?: Record<string, unknown>;
  }) =>
    request<{ ok: boolean; error: string | null }>('/api/visuals/generate-video-from-reference', {
      method: 'POST',
      body: json({
        prompt: params.prompt,
        video_path: params.videoPath,
        image_paths: params.imagePaths ?? null,
        options: params.options ?? {},
      }),
    }),

  generateMusic: (params: { prompt: string; negativePrompt?: string }) =>
    request<{ ok: boolean; error: string | null }>('/api/visuals/generate-music', {
      method: 'POST',
      body: json({ prompt: params.prompt, options: { negative_prompt: params.negativePrompt } }),
    }),
};

// ---- city (/api/city) -----------------------------------------------------

export const city = {
  // A MediaItem's `url` is a path relative to citystate/data/ (see
  // store.py's _relocate_media_file: str(dest.relative_to(DATA_DIR))),
  // not a servable URL by itself -- GET /api/city/files/<path> is what
  // actually serves it.
  fileUrl: (mediaUrl: string) => `/api/city/files/${mediaUrl}`,

  getAgent: (agentId: string) => request<AgentRecord>(`/api/city/agents/${agentId}`),

  addMedia: (params: {
    entityId: string;
    kind: 'image' | 'video';
    url: string;
    localPath?: string;
    prompt?: string;
    tag?: string;
  }) =>
    request<{ ok: boolean; media: MediaItem[] }>('/api/city/media', {
      method: 'POST',
      body: json({
        entity_id: params.entityId,
        kind: params.kind,
        url: params.url,
        local_path: params.localPath,
        prompt: params.prompt,
        tag: params.tag,
      }),
    }),

  removeMedia: (entityId: string, mediaId: string) =>
    request<{ ok: boolean }>(`/api/city/media/${entityId}/${mediaId}`, { method: 'DELETE' }),
};

// ---- graph (/api/graph) -- the node-based UI's own canvas persistence --

export class GraphRevConflict extends Error {
  current: GraphDoc;
  constructor(current: GraphDoc) {
    super('graph document has moved on -- rev conflict');
    this.current = current;
  }
}

export const graph = {
  get: (scope: string) => request<GraphDoc>(`/api/graph/${encodeURIComponent(scope)}`),

  put: async (scope: string, doc: Omit<GraphDoc, 'scope' | 'updated'>): Promise<GraphDoc> => {
    const res = await fetch(`/api/graph/${encodeURIComponent(scope)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: json(doc),
    });
    const body = await res.json();
    if (res.status === 409) throw new GraphRevConflict(body.current as GraphDoc);
    if (!res.ok) throw new Error(body.error ?? `${res.status} ${res.statusText}`);
    return body as GraphDoc;
  },
};

// ---- styles (/api/styles) -- the global, reusable style library --------

export const stylesApi = {
  list: () => request<{ styles: Style[] }>('/api/styles/'),

  create: (params: { name: string; stylePrompt: string; negativePrompt?: string; strength?: number }) =>
    request<{ style: Style }>('/api/styles/', {
      method: 'POST',
      body: json({ name: params.name, style_prompt: params.stylePrompt, negative_prompt: params.negativePrompt, strength: params.strength }),
    }),

  update: (
    id: string,
    patch: Partial<{ name: string; stylePrompt: string; negativePrompt: string; strength: number; referenceImages: string[] }>,
  ) =>
    request<{ style: Style }>(`/api/styles/${id}`, {
      method: 'PUT',
      body: json({
        name: patch.name,
        style_prompt: patch.stylePrompt,
        negative_prompt: patch.negativePrompt,
        strength: patch.strength,
        reference_images: patch.referenceImages,
      }),
    }),

  remove: (id: string) => request<{ ok: boolean }>(`/api/styles/${id}`, { method: 'DELETE' }),
};
