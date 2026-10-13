import type { VideoWorkflowDefaults } from '../../api/types';
import { NumberField } from './NumberField';

// The Video node's ComfyUI options -- the inputs of its MiniMax H3 workflow
// (visuals/data/config.yaml's video_workflow / reference_video_workflow
// .options). Blank means the workflow's own value; `defaults` are those
// values (GET /api/visuals/providers' video_workflows), so what's shown is
// what the workflow will use.
export interface VideoOptionValues {
  duration?: number; // seconds (the workflow turns it into frames at 24 fps)
  megapixels?: number; // with the aspect ratio -> the frame size
  steps?: number;
  sampler?: string;
  scheduler?: string;
  seed?: number; // blank = a new random seed each time
}

// The megapixel steps from the workflow's "Size Settings Reference" note.
const MEGAPIXELS = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.98, 1.0, 1.2, 1.5, 1.8, 2.0];
// ComfyUI's own sampler and scheduler names (comfy/samplers.py), the common ones.
const SAMPLERS = ['res_multistep', 'euler', 'euler_ancestral', 'dpmpp_2m', 'dpmpp_2m_sde', 'dpmpp_3m_sde',
  'uni_pc', 'deis', 'lcm', 'er_sde', 'sa_solver'];
const SCHEDULERS = ['simple', 'normal', 'karras', 'exponential', 'sgm_uniform', 'beta', 'linear_quadratic', 'kl_optimal'];
// Before the server's answer arrives (the image-to-video workflow's values).
const FALLBACK: Required<VideoWorkflowDefaults> = { duration: 5, megapixels: 0.4, steps: 20, sampler: 'res_multistep', scheduler: 'simple' };

// The frame ComfyUI's Resolution Selector makes: `mp` megapixels (of
// 1024x1024) at the aspect ratio, each side rounded to a multiple of 32.
export function frameSize(mp: number, aspect: string): [number, number] {
  const [w, h] = aspect.split(':').map(Number);
  const total = mp * 1024 * 1024;
  const round = (x: number) => Math.max(32, Math.round(x / 32) * 32);
  return [round(Math.sqrt((total * w) / h)), round(Math.sqrt((total * h) / w))];
}

// Duration and resolution: always on show, like the workflow's own inputs.
export function VideoSizeOptions({
  value,
  defaults,
  aspectRatio,
  onChange,
}: {
  value: VideoOptionValues;
  defaults?: VideoWorkflowDefaults;
  aspectRatio: string;
  onChange: (v: VideoOptionValues) => void;
}) {
  const d = { ...FALLBACK, ...(defaults ?? {}) };
  const set = (patch: Partial<VideoOptionValues>) => onChange({ ...value, ...patch });
  const mp = value.megapixels ?? d.megapixels;
  const choices = MEGAPIXELS.includes(mp) ? MEGAPIXELS : [...MEGAPIXELS, mp].sort((a, b) => a - b);
  return (
    <div className="node-controls node-video-size nodrag">
      <label title="Clip length in seconds -- the workflow turns it into frames at 24 fps (MiniMax H3 is trained on ~5-15 s)">
        duration
        <NumberField value={value.duration ?? d.duration} min={1} max={20} decimals title="Clip length in seconds"
          onCommit={(v) => set({ duration: v })} />
        s
      </label>
      <label title="The Resolution Selector's megapixels: with the aspect ratio, the frame size">
        resolution
        <select className="node-select" value={mp} onChange={(e) => set({ megapixels: Number(e.target.value) })}>
          {choices.map((m) => {
            const [w, h] = frameSize(m, aspectRatio);
            return (
              <option key={m} value={m}>
                {w}×{h} · {m} MP{m === d.megapixels ? ' (workflow)' : ''}
              </option>
            );
          })}
        </select>
      </label>
    </div>
  );
}

// Steps, sampler, scheduler and seed, folded away.
export function VideoOptions({
  value,
  defaults,
  lastSeed,
  onChange,
}: {
  value: VideoOptionValues;
  defaults?: VideoWorkflowDefaults;
  lastSeed?: number;
  onChange: (v: VideoOptionValues) => void;
}) {
  const d = { ...FALLBACK, ...(defaults ?? {}) };
  const set = (patch: Partial<VideoOptionValues>) => onChange({ ...value, ...patch });
  return (
    <details className="node-options nodrag">
      <summary>sampling options</summary>
      <div className="node-options-grid">
        <label>steps</label>
        <NumberField value={value.steps ?? d.steps} min={1} max={100} title="Sampling steps"
          onCommit={(v) => set({ steps: v })} />

        <label>sampler</label>
        <select className="node-select" value={value.sampler ?? d.sampler} onChange={(e) => set({ sampler: e.target.value })}>
          {(SAMPLERS.includes(value.sampler ?? d.sampler) ? SAMPLERS : [...SAMPLERS, value.sampler ?? d.sampler]).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>

        <label>scheduler</label>
        <select className="node-select" value={value.scheduler ?? d.scheduler} onChange={(e) => set({ scheduler: e.target.value })}>
          {(SCHEDULERS.includes(value.scheduler ?? d.scheduler) ? SCHEDULERS : [...SCHEDULERS, value.scheduler ?? d.scheduler]).map((s) => (
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
        reset everything to the workflow's values
      </button>
    </details>
  );
}
