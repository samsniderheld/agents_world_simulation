// The aspect-ratio dropdown shared by every image/video node. The value is
// sent as `options.aspect_ratio`, which every configured fal endpoint
// accepts (text-to-image, image edit, image-to-video, reference-to-video --
// verified against their published schemas) and the local provider maps to
// a pixel size (visuals/providers/local.py).
export type AspectRatio = '16:9' | '9:16';

export function AspectSelect({ value, onChange }: { value: AspectRatio; onChange: (v: AspectRatio) => void }) {
  return (
    <select
      className="node-select node-aspect-select nodrag"
      value={value}
      title="Aspect ratio"
      onChange={(e) => onChange(e.target.value as AspectRatio)}
    >
      <option value="16:9">16:9 landscape</option>
      <option value="9:16">9:16 portrait</option>
    </select>
  );
}
