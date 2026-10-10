import type { VisualsProviders } from '../../api/types';

const LABELS: Record<string, string> = { fal: 'fal.ai', comfyui: 'ComfyUI', local: 'local (Mac)' };

// Which provider an Image or Video node generates with. Blank = the server's
// default for that kind (VISUALS_IMAGE_PROVIDER / VISUALS_VIDEO_PROVIDER);
// only providers that can make that kind are offered.
export function ProviderSelect({
  kind,
  value,
  info,
  onChange,
}: {
  kind: 'image' | 'video';
  value: string;
  info: VisualsProviders | null;
  onChange: (v: string) => void;
}) {
  const choices = (info?.available ?? []).filter((p) => kind === 'image' || info?.capabilities[p]?.supports_video);
  const fallback = info ? LABELS[info.defaults[kind]] ?? info.defaults[kind] : '…';
  return (
    <select
      className="node-select node-aspect-select nodrag"
      value={value}
      title={`Which service makes this ${kind}`}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">default ({fallback})</option>
      {choices.map((p) => (
        <option key={p} value={p}>
          {LABELS[p] ?? p}
        </option>
      ))}
    </select>
  );
}
