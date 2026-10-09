// The aspect-ratio dropdown shared by every image/video node. The value is
// sent as `options.aspect_ratio`, which every configured fal endpoint
// accepts (text-to-image, image edit, image-to-video, reference-to-video --
// verified against their published schemas) and the local provider maps to
// a pixel size (visuals/providers/local.py).
export type AspectRatio = '16:9' | '9:16' | '1:1';

// `square` adds 1:1 -- the image models take it; the video models only do
// 16:9 and 9:16, so the Video node leaves it off.
export function AspectSelect({ value, onChange, square = false }: { value: AspectRatio; onChange: (v: AspectRatio) => void; square?: boolean }) {
  return (
    <select
      className="node-select node-aspect-select nodrag"
      value={value}
      title="Aspect ratio"
      onChange={(e) => onChange(e.target.value as AspectRatio)}
    >
      <option value="16:9">16:9 landscape</option>
      <option value="9:16">9:16 portrait</option>
      {square && <option value="1:1">1:1 square</option>}
    </select>
  );
}

// The image size picker next to AspectSelect on the Image node, sent as
// `options.resolution`: fal's image models take "1K"/"2K" directly; the
// ComfyUI provider turns it into the canvas size and the reference images'
// pixel budget (visuals/providers/comfyui.py). The local provider ignores it.
export type Resolution = '1K' | '2K';

export function ResolutionSelect({ value, onChange }: { value: Resolution; onChange: (v: Resolution) => void }) {
  return (
    <select
      className="node-select node-aspect-select nodrag"
      value={value}
      title="Resolution: 1K is about 1 megapixel, 2K about 4"
      onChange={(e) => onChange(e.target.value as Resolution)}
    >
      <option value="1K">1K</option>
      <option value="2K">2K</option>
    </select>
  );
}
