// Types mirror exactly what the Flask backend sends today -- verified by
// reading history/generate.py's to_json(), citystate/store.py's get()/
// get_agent()/add_media(), agents/routes.py + recorder.py, and
// visuals/jobs.py, rather than guessed from the design docs. Field names
// and id prefixes (fig_/place_/char_) are the real ones.

export type EntityId = string;
export type FigureId = `fig_${string}`;
export type PlaceId = `place_${string}`;
export type CharacterId = `char_${string}`;

// GET /api/history/cities -- a lightweight summary, not the full
// composed city (see citystate/store.py's list_cities() docstring for
// why it's cheaper than get()).
export interface CitySummary {
  id: string;
  generated_at: string;
  summary: string;
  figure_count: number;
  place_count: number;
  character_count: number;
  is_active: boolean;
  // The theme the city was generated with (theme.py); none = the default.
  theme?: { id: string; name: string } | null;
}

// GET /api/themes -- a city theme (themes/*.yaml, or uploaded).
export interface ThemeSummary {
  id: string;
  name: string;
  description: string;
  present_year: number | null;
  source: string; // "built-in" | "uploaded" | "city"
}

export interface Era {
  id: string;
  name: string;
  start_year: number;
  end_year: number;
  description: string;
}

export interface Figure {
  id: FigureId;
  name: string;
  role: string;
  domain: string;
  era_id: string;
  birth_year: number;
  death_year: number | null;
  alive: boolean;
  properties: {
    allies?: string[];
    rivals?: string[];
    founded_places?: PlaceId[];
    [key: string]: unknown;
  };
}

export type PlaceStatus = 'active' | 'destroyed' | 'closed';

export interface PlaceHistoryEntry {
  year: number;
  event_id?: string;
  template_id?: string;
  figure_id?: FigureId | null;
  gospel_text: string;
}

export interface Place {
  id: PlaceId;
  name: string;
  place_type: string;
  domain: string;
  founded_year: number;
  closed_year: number | null;
  status: PlaceStatus;
  founding_figure_id: FigureId | null;
  current_owner_figure_id: FigureId | null;
  architecture: string;
  properties: { tags?: string[]; [key: string]: unknown };
  history: PlaceHistoryEntry[];
}

export interface HistoryEvent {
  id: string;
  era_id: string;
  year: number;
  template_id: string;
  figure_id: FigureId | null;
  place_id: PlaceId | null;
  gospel_text: string;
  [key: string]: unknown;
}

export interface Treatment {
  created_at: string;
  run_started_at: string | null;
  text: string;
}

export interface MediaItem {
  id: string;
  kind: 'image' | 'video';
  url: string;
  local_path: string;
  prompt: string;
  tag: string;
  created_at: string;
}

export interface CharacterHistoryEntry {
  year: number;
  gospel_text: string;
  [key: string]: unknown;
}

// Verified against a real generated character record -- age/occupation/
// quirk/bio/founder_id/history are reliably present in practice, but kept
// optional since history/characters.yaml's templates could in principle
// omit one.
export interface Character {
  id: CharacterId;
  name: string;
  age?: number;
  occupation?: string;
  quirk?: string;
  bio?: string;
  place_id?: PlaceId;
  place_name?: string;
  founder_id?: FigureId;
  history?: CharacterHistoryEntry[];
  [key: string]: unknown;
}

// Verified against agents/recorder.py's docstring (the authoritative
// event schema) -- kind-specific fields are all optional since they vary
// by kind; every event always has kind/tick/agent.
export type AgentEventKind =
  | 'plan'
  | 'decompose'
  | 'observe'
  | 'react'
  | 'continue'
  | 'memory'
  | 'focal'
  | 'insight'
  | 'action'
  | 'dialogue'
  | 'move'
  | 'reflect_pause'
  | 'treatment'
  // CITY mode (agents/city/recorder.py) only:
  | 'status'
  | 'encounter'
  | 'promotion'
  | 'metrics'
  | 'schedule'
  | 'schedules'
  | 'moves'
  | 'tick_summary';

export interface AgentEvent {
  kind: AgentEventKind;
  tick: number;
  agent: string | null;
  items?: string[]; // plan
  broad_step?: string; // decompose
  text?: string; // observe/react/focal/insight/action/dialogue/treatment
  memory_kind?: string; // memory
  importance?: number; // memory
  evidence?: number[]; // memory/insight
  location?: string; // action
  time?: string; // action
  listener?: string; // dialogue
  from_location?: string; // move
  to_location?: string; // move
  [key: string]: unknown;
}

// citystate/store.py's append_agent_run() -- one entry per run this
// agent participated in.
export interface AgentRun {
  started_at: string | null;
  meta: Record<string, unknown>;
  events: AgentEvent[];
}

export interface AgentPlan {
  run_started_at: string | null;
  tick: number;
  items: string[];
}

// GET /api/city/agents/<id> -- a character's full on-disk record. Plans/
// runs/treatments only ever live on disk, never in the composed
// HistoryData.characters list below.
export interface AgentRecord extends Character {
  media: MediaItem[];
  plans: AgentPlan[];
  runs: AgentRun[];
  treatments: Treatment[];
}

// GET /api/history/data -- store.get()'s composed dict.
export interface HistoryData {
  generated_at: string;
  summary: string;
  eras: Era[];
  figures: Figure[];
  places: Place[];
  events: HistoryEvent[];
  characters: Character[];
  // Keyed by BOTH place_* and char_* ids.
  media: Record<EntityId, MediaItem[]>;
}

// agents/routes.py's GET /state -- recorder.get_agents()'s per-agent rows.
export interface AgentStateRow {
  name: string;
  color: string;
  age: number;
  traits: string;
  location: string;
}

export type JobPhase = 'idle' | 'running' | 'done' | 'error';

export interface JobStatus {
  phase: JobPhase;
  error: string | null;
  // /api/agents/state only, and only for a CITY run: "city".
  mode?: string;
}

export interface AgentsState {
  status: JobStatus;
  // For a CITY run, only the heroes -- background residents are counted
  // in `population`, not listed.
  agents: AgentStateRow[];
  meta: {
    // "scene" or "city"; a run from before modes existed has none (= scene).
    mode?: string;
    provider: string;
    chat_model: string;
    embed_model: string | null;
    context_tokens: number | null;
    ticks: number;
    [key: string]: unknown;
  };
  started_at: string | null;
  event_count: number;
  population?: { heroes: number; background: number; [key: string]: unknown };
  // CITY runs: the last tick's metrics event.
  metrics?: CityMetrics | null;
}

// One CITY tick's "metrics" event (agents/city/world.py's _record_metrics).
export interface CityMetrics {
  tick: number;
  time?: string;
  seconds: number;
  waves: Record<string, number>;
  requests: number;
  tokens_in: number;
  tokens_out: number;
  retries: number;
  failures: number;
  repairs: number;
  backpressure: number;
  tokens_per_second: number;
  calls_by_tier: Record<string, number>;
  calls_by_kind: Record<string, number>;
  calls_per_hero: number;
  calls_per_background: number;
  heroes: number;
  background: number;
  encounters: number;
  conversations: number;
}

// GET /api/visuals/providers's capabilities block -- what the canvas can
// honor for the currently active provider (see visuals/providers/
// __init__.py's CAPABILITIES docstring for how each was verified).
export interface ProviderCapabilities {
  supports_reference_images: boolean;
  supports_video: boolean;
  supports_music: boolean;
}

// The global style library (visuals/styles.py) -- independent of any
// city, reusable across canvases. Just a text prompt plus reference
// images; the current fal/Gemini provider has no negative-prompt or
// CFG-strength-style parameter, so the Style model doesn't carry either.
export interface Style {
  id: string;
  name: string;
  style_prompt: string;
  reference_images: string[];
}

// GET/PUT /api/graph/<scope> -- see citystate/graph_store.py's docstring.
// Deliberately opaque on the backend: `data` shape is per node `type`,
// known only to the frontend (see flow/nodes/*).
export interface GraphNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  // Set once a node has been drag-resized (NodeShell's <NodeResizer/>) --
  // undefined until then, so an un-resized node keeps its CSS default
  // size rather than being pinned to whatever width/height a first render
  // happened to measure.
  width?: number;
  height?: number;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  sourceHandle: string;
  target: string;
  targetHandle: string;
}

export interface GraphDoc {
  scope: string;
  version: number;
  rev: number;
  updated: string | null;
  viewport: { x: number; y: number; zoom: number };
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export type VisualsJobKind = 'image' | 'video' | 'video_reference' | 'music';

// Verified against both providers/fal.py and providers/local.py's
// generate_image() -- `url` here is relative to visuals/data/ (see
// storage.py's relative_path docstring), NOT servable directly; it only
// matters as a passthrough into POST /api/city/media, which re-derives
// the real citystate-relative url from `local_path` during relocation.
export interface GeneratedImage {
  local_path: string;
  url: string;
  width: number | null;
  height: number | null;
  content_type: string | null;
}

export interface ImageGenResult {
  kind: 'image';
  images: GeneratedImage[];
  description: string;
}

// Verified against providers/fal.py's generate_video()/_save_video() --
// the only provider that implements video at all (LocalProvider raises
// NotImplementedError for it).
export interface GeneratedVideo {
  local_path: string;
  url: string;
  content_type: string | null;
  file_size: number | null;
}

export interface VideoGenResult {
  kind: 'video' | 'video_reference';
  video: GeneratedVideo;
}

// Verified against providers/fal.py's generate_music() (the only
// provider that implements it -- LocalProvider has no music support).
export interface GeneratedAudio {
  local_path: string;
  url: string;
  content_type: string | null;
  file_size: number | null;
}

export interface MusicGenResult {
  kind: 'music';
  audio: GeneratedAudio;
}

// visuals/jobs.py's get_result() -- `kind` plus the active provider's
// generate_* return dict merged in flat.
export type VisualsResult = ImageGenResult | VideoGenResult | MusicGenResult;

// A saved graph (citystate/graph_library.py): a canvas's nodes/edges plus
// the inner canvas of every Storyboard on it, keyed by the scope it had
// when saved.
export interface GraphBody {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SavedGraphSummary {
  id: string;
  name: string;
  created: string;
  source_scope: string | null;
  node_count: number;
  storyboard_count: number;
}

export interface SavedGraph {
  id: string;
  name: string;
  created: string;
  source_scope: string | null;
  root: GraphBody;
  storyboards: Record<string, GraphBody>;
}

// GET /api/history/population -- history/population.py's job status.
export interface PopulationStatus {
  phase: 'idle' | 'running' | 'done' | 'error';
  error: string | null;
  total: number;
  done: number;
  current: string;
  log: string[];
}

// A Style node's prompt + reference images, as the Population node sends it.
export interface PopulationStyle {
  prompt: string;
  reference_images: string[];
}

// GET /api/agents/city/zoom -- what a CITY run can be zoomed into.
export interface CityZoomOptions {
  started_at: string;
  places: { name: string; place_id: string; heroes: number; people: number }[];
  ticks: number;
  times: string[];
  tick_minutes: number;
  start_time: string;
}

// POST /api/agents/city/zoom -- a SCENE run's cast, place and time for one
// place and window of a CITY run (agents/city/zoom.py). `characters` are
// background residents just promoted to saved characters.
export interface CityZoomResult {
  started_at: string;
  place: string;
  place_id: string | null;
  tick_from: number;
  tick_to: number;
  start_time: string;
  tick_minutes: number;
  ticks: number;
  directive: string | null;
  agent_names: string[];
  agent_ids: string[];
  characters: Character[];
  promoted: string[];
}

// POST /api/agents/city/report and /city/ask.
export interface CityInsight {
  text: string;
  lines_used: number;
  lines_total: number;
  // "live" (the run in memory) or "saved" (the latest saved run, after a restart)
  source: string;
  started_at: string;
}
