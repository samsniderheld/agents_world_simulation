import { NumberField } from './NumberField';

// The Video node's ComfyUI options -- the inputs of the MiniMax H3 image-to-
// video workflow (visuals/data/config.yaml's video_workflow.options). Blank
// means the workflow's own value (duration: 5 s).
export interface VideoOptionValues {
  duration?: number; // seconds (the workflow turns it into frames at 24 fps)
  megapixels?: number; // with the aspect ratio -> the frame size
  steps?: number;
  sampler?: string;
  scheduler?: string;
  seed?: number; // blank = a new random seed each time
}

// 16:9 frame sizes are what ComfyUI's Resolution Selector makes of each.
const RESOLUTIONS: { mp: number; label: string }[] = [
  { mp: 0.4, label: '480p (864x480)' },
  { mp: 0.6, label: '600p (1056x608)' },
  { mp: 0.9, label: '720p (1280x736)' },
  { mp: 2.0, label: '1080p (1920x1088)' },
];
// ComfyUI's own sampler and scheduler names (comfy/samplers.py), the common ones.
const SAMPLERS = ['res_multistep', 'euler', 'euler_ancestral', 'dpmpp_2m', 'dpmpp_2m_sde', 'dpmpp_3m_sde',
  'uni_pc', 'deis', 'lcm', 'er_sde', 'sa_solver'];
const SCHEDULERS = ['simple', 'normal', 'karras', 'exponential', 'sgm_uniform', 'beta', 'linear_quadratic', 'kl_optimal'];
const DEFAULTS = { duration: 5, megapixels: 0.4, steps: 20, sampler: 'res_multistep', scheduler: 'simple' };

export function VideoOptions({
  value,
  lastSeed,
  onChange,
}: {
  value: VideoOptionValues;
  lastSeed?: number;
  onChange: (v: VideoOptionValues) => void;
}) {
  const set = (patch: Partial<VideoOptionValues>) => onChange({ ...value, ...patch });
  return (
    <details className="node-options nodrag">
      <summary>ComfyUI options</summary>
      <div className="node-options-grid">
        <label>duration (s)</label>
        <NumberField value={value.duration ?? DEFAULTS.duration} min={1} max={20} title="Clip length in seconds (trained on ~5-15)"
          onCommit={(v) => set({ duration: v })} />

        <label>resolution</label>
        <select className="node-select" value={value.megapixels ?? DEFAULTS.megapixels}
          onChange={(e) => set({ megapixels: Number(e.target.value) })}>
          {RESOLUTIONS.map((r) => (
            <option key={r.mp} value={r.mp}>
              {r.label}
            </option>
          ))}
        </select>

        <label>steps</label>
        <NumberField value={value.steps ?? DEFAULTS.steps} min={1} max={100} title="Sampling steps"
          onCommit={(v) => set({ steps: v })} />

        <label>sampler</label>
        <select className="node-select" value={value.sampler ?? DEFAULTS.sampler} onChange={(e) => set({ sampler: e.target.value })}>
          {SAMPLERS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <label>scheduler</label>
        <select className="node-select" value={value.scheduler ?? DEFAULTS.scheduler} onChange={(e) => set({ scheduler: e.target.value })}>
          {SCHEDULERS.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <label>seed</label>
        <div className="node-options-seed">
          <input
            className="node-select"
            inputMode="numeric"
            placeholder="random"
            value={value.seed ?? ''}
            title="Blank: a new random seed each time. A number repeats a result."
            onChange={(e) => {
              const digits = e.target.value.replace(/[^0-9]/g, '');
              set({ seed: digits ? Number(digits) : undefined });
            }}
          />
          {lastSeed != null && lastSeed !== value.seed && (
            <button className="node-link-btn" title="Use the seed of the last clip" onClick={() => set({ seed: lastSeed })}>
              use last ({lastSeed})
            </button>
          )}
        </div>
      </div>
      <button className="node-link-btn" onClick={() => onChange({})}>
        reset to the workflow's defaults
      </button>
    </details>
  );
}
