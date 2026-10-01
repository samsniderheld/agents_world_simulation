// Thin typed wrappers over the Flask JSON API -- one function per route,
// request/response shapes verified against the real route handlers
// (history/, agents/, visuals/ and citystate/'s routes.py files, plus
// citystate/graph_routes.py and visuals/styles_routes.py), not guessed.

import type {
  AgentRecord,
  AgentsState,
  Character,
  CitySummary,
  GraphBody,
  GraphDoc,
  HistoryData,
  JobStatus,
  MediaItem,
  PopulationStatus,
  PopulationStyle,
  ProviderCapabilities,
  SavedGraph,
  SavedGraphSummary,
  Style,
  Treatment,
  VisualsResult,
  CityZoomOptions,
  CityZoomResult,
  CityInsight,
  ThemeSummary,
  BackgroundResident,
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
    // A theme id (GET /api/themes); omitted = the city's own theme when
    // regenerating it, else the default theme.
    themeId?: string;
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
          theme_id: params.themeId,
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

  // For a CITY run `since` is a cursor and `tier` picks "hero" (default),
  // "background" or "all"; SCENE runs ignore it.
  events: (since = 0, tier?: string) =>
    request<{ events: unknown[]; next: number; dropped?: number; started_at?: string | null }>(
      `/api/agents/events?since=${since}${tier ? `&tier=${tier}` : ''}`,
    ),

  run: (params: {
    agentNames: string[];
    ticks?: number;
    // Simulated minutes per tick; omitted = server default (config.TICK_MINUTES).
    tickMinutes?: number;
    // Simulated start time of day, "HH:MM"; omitted = 06:00.
    startTime?: string;
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
    // Free-text "guide how the characters are interacting" note from the
    // Simulation node -- threaded through to every plan/decompose/react/
    // dialogue call this run makes (see agents/textutil.directive_block).
    directive?: string;
  }) =>
    request<{ ok: boolean; error: string | null }>('/api/agents/run', {
      method: 'POST',
      body: json({
        agent_names: params.agentNames,
        ticks: params.ticks ?? 8,
        tick_minutes: params.tickMinutes,
        start_time: params.startTime,
        provider: params.provider,
        tick_sleep: params.tickSleep ?? 0,
        chat_model: params.chatModel,
        embed_model: params.embedModel,
        context_tokens: params.contextTokens,
        verbose: params.verbose ?? false,
        place_id: params.placeId,
        location_mode: params.locationMode ?? 'grounded',
        directive: params.directive,
      }),
    }),

  // A CITY run (agents/city/) -- same /run endpoint and job slot as a
  // SCENE run, with mode "city".
  runCity: (params: {
    agentNames: string[];
    backgroundCount: number;
    profile?: string;
    heroProvider?: string;
    heroModel?: string;
    backgroundProvider?: string;
    backgroundModel?: string;
    ticks: number;
    tickMinutes?: number;
    startTime?: string;
    directive?: string;
    placeId?: string;
    persistHeroMemories?: boolean;
    seed?: number;
  }) =>
    request<{ ok: boolean; error: string | null }>('/api/agents/run', {
      method: 'POST',
      body: json({
        mode: 'city',
        agent_names: params.agentNames,
        background_count: params.backgroundCount,
        profile: params.profile,
        hero_provider: params.heroProvider,
        hero_model: params.heroModel,
        background_provider: params.backgroundProvider,
        background_model: params.backgroundModel,
        ticks: params.ticks,
        tick_minutes: params.tickMinutes,
        start_time: params.startTime,
        directive: params.directive,
        place_id: params.placeId,
        location_mode: params.placeId ? 'convene' : 'grounded',
        persist_hero_memories: params.persistHeroMemories ?? true,
        seed: params.seed,
      }),
    }),

  stop: () => request<{ ok: boolean }>('/api/agents/stop', { method: 'POST' }),

  // CITY-only controls (agents/routes.py's /city/*).
  cityPause: () => request<{ ok: boolean; error?: string }>('/api/agents/city/pause', { method: 'POST' }),
  cityResume: () => request<{ ok: boolean }>('/api/agents/city/resume', { method: 'POST' }),
  cityPromote: (name: string) =>
    request<{ ok: boolean; error: string | null }>('/api/agents/city/promote', { method: 'POST', body: json({ name }) }),
  // "What's going on in the city": a briefing, or a question answered from
  // the current/latest CITY run's log (agents/city/insight.py).
  cityReport: (previous?: string) =>
    request<CityInsight>('/api/agents/city/report', { method: 'POST', body: json({ previous }) }),
  cityAsk: (question: string) =>
    request<CityInsight>('/api/agents/city/ask', { method: 'POST', body: json({ question }) }),
  cityResidents: () => request<{ residents: BackgroundResident[] }>('/api/agents/city/residents'),
  cityResidentToCharacter: (id: string) =>
    request<{ character: Character }>(`/api/agents/city/residents/${encodeURIComponent(id)}/character`, { method: 'POST' }),
  cityZoomOptions: () => request<CityZoomOptions>('/api/agents/city/zoom'),
  cityZoom: (params: { place: string; tickFrom: number; tickTo: number; startedAt?: string }) =>
    request<CityZoomResult>('/api/agents/city/zoom', {
      method: 'POST',
      body: json({ place: params.place, tick_from: params.tickFrom, tick_to: params.tickTo, started_at: params.startedAt }),
    }),
  cityProfiles: () =>
    request<{ profiles: Record<string, { label: string; population_cap: number; hero_cap: number }>; detected: string }>(
      '/api/agents/city/profiles',
    ),

  generateTreatment: (
    agentId: string,
    params?: {
      provider?: string;
      model?: string;
      agentIds?: string[];
      placeIds?: string[];
      // CITY runs only: narrow the transcript to one place / window of ticks.
      place?: string;
      tickFrom?: number;
      tickTo?: number;
    },
  ) =>
    request<{ treatment: Treatment }>('/api/agents/treatment', {
      method: 'POST',
      body: json({
        agent_id: agentId,
        provider: params?.provider,
        model: params?.model,
        // Treatment node's own agent:in/place:in ports -- context the
        // user explicitly wired in, independent of who/where the run's
        // own transcript says was involved (see agents/routes.py's
        // POST /treatment docstring).
        agent_ids: params?.agentIds,
        place_ids: params?.placeIds,
        place: params?.place,
        tick_from: params?.tickFrom,
        tick_to: params?.tickTo,
      }),
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

  providers: () =>
    request<{ available: string[]; current: string; capabilities: Record<string, ProviderCapabilities> }>('/api/visuals/providers'),

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

// ---- the Population node (/api/history/population) -- history/population.py

export const populationApi = {
  start: (params: { count: number; characterStyle?: PopulationStyle; locationStyle?: PopulationStyle; withImages?: boolean }) =>
    request<{ ok: boolean; error: string | null }>('/api/history/population', {
      method: 'POST',
      body: json({
        count: params.count,
        character_style: params.characterStyle,
        location_style: params.locationStyle,
        with_images: params.withImages ?? true,
      }),
    }),
  status: () => request<PopulationStatus>('/api/history/population'),
  stop: () => request<{ ok: boolean }>('/api/history/population/stop', { method: 'POST' }),
};

// ---- saved graphs (/api/graph-library) -- see citystate/graph_library.py ---

export const graphLibrary = {
  list: () => request<{ graphs: SavedGraphSummary[] }>('/api/graph-library/'),
  get: (id: string) => request<{ graph: SavedGraph }>(`/api/graph-library/${encodeURIComponent(id)}`),
  save: (params: { name: string; root: GraphBody; storyboards: Record<string, GraphBody>; sourceScope: string }) =>
    request<{ graph: { id: string; name: string } }>('/api/graph-library/', {
      method: 'POST',
      body: json({ name: params.name, root: params.root, storyboards: params.storyboards, source_scope: params.sourceScope }),
    }),
  remove: (id: string) => request<{ ok: boolean }>(`/api/graph-library/${encodeURIComponent(id)}`, { method: 'DELETE' }),
};

// ---- styles (/api/styles) -- the global, reusable style library --------

export const stylesApi = {
  list: () => request<{ styles: Style[] }>('/api/styles/'),

  // reference_images stores real absolute filesystem paths (needed as-is
  // by the provider's image_paths, see visuals/routes.py's
  // _style_reference_images()) -- not a /api/visuals/files/... relative
  // url, so displaying one goes through this dedicated route instead of
  // visuals.fileUrl().
  referenceImageUrl: (path: string) => `/api/styles/reference-image?path=${encodeURIComponent(path)}`,

  create: (params: { name: string; stylePrompt: string }) =>
    request<{ style: Style }>('/api/styles/', {
      method: 'POST',
      body: json({ name: params.name, style_prompt: params.stylePrompt }),
    }),

  update: (id: string, patch: Partial<{ name: string; stylePrompt: string; referenceImages: string[] }>) =>
    request<{ style: Style }>(`/api/styles/${id}`, {
      method: 'PUT',
      body: json({
        name: patch.name,
        style_prompt: patch.stylePrompt,
        reference_images: patch.referenceImages,
      }),
    }),

  remove: (id: string) => request<{ ok: boolean }>(`/api/styles/${id}`, { method: 'DELETE' }),
};

// ---- city themes (/api/themes) -- theme.py / theme_routes.py
export const themesApi = {
  list: () => request<{ themes: ThemeSummary[]; default: string; active_city_theme: ThemeSummary | null }>('/api/themes'),
  // Sends the YAML as the raw body. A rejected theme comes back as
  // { ok: false, problems: [...] } (status 400) -- returned, not thrown, so
  // the dialog can list every problem.
  upload: async (text: string): Promise<{ ok: boolean; theme?: ThemeSummary; problems?: string[] }> => {
    const res = await fetch('/api/themes', { method: 'POST', headers: { 'Content-Type': 'application/x-yaml' }, body: text });
    const body = await res.json().catch(() => null);
    if (body && typeof body.ok === 'boolean') return body;
    return { ok: false, problems: [`upload failed (${res.status} ${res.statusText})`] };
  },
  remove: (id: string) => request<{ ok: boolean; error?: string }>(`/api/themes/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  fileUrl: (id: string) => `/api/themes/${encodeURIComponent(id)}/file`,
  cityFileUrl: (cityId: string) => `/api/themes/city/${encodeURIComponent(cityId)}/file`,
};
