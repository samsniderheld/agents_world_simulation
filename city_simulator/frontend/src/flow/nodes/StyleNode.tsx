import { useEffect, useState } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { stylesApi, visuals } from '../../api/client';
import type { Style } from '../../api/types';
import { NodeShell } from './NodeShell';
import { Port } from './Port';
import { useProviderCapabilities } from './useProviderCapabilities';

export interface StyleNodeData extends Record<string, unknown> {
  styleId: string;
  // Lifted into this node's own data once loaded/edited (rather than
  // kept only in local component state) -- Frame/Video nodes need to
  // read a connected Style's current prompt/references when *they*
  // generate, and the only place cross-node reads happen is the shared
  // nodes array (see pipeline.ts's enrichPipelineNodes).
  style?: Style;
  onLoaded: (nodeId: string, style: Style) => void;
  onUpdate: (nodeId: string, patch: Partial<Style>) => void;
}

export type StyleNodeType = Node<StyleNodeData, 'style'>;

export function StyleNode({ id, data, selected }: NodeProps<StyleNodeType>) {
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const style = data.style;
  const capabilities = useProviderCapabilities();

  // Edited locally so onGenerate (fed by data.onUpdate) sees keystrokes
  // right away without round-tripping to the backend, and Save is a
  // separate, explicit commit of that local state -- not tied to blur.
  const [name, setName] = useState(style?.name ?? '');
  const [prompt, setPrompt] = useState(style?.style_prompt ?? '');
  const dirty = Boolean(style) && (name !== style!.name || prompt !== style!.style_prompt);

  useEffect(() => {
    if (style) return;
    stylesApi
      .list()
      .then((res) => {
        const found = res.styles.find((s) => s.id === data.styleId);
        if (found) data.onLoaded(id, found);
        else setError('style not found in library');
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data.styleId, style]);

  useEffect(() => {
    if (!style) return;
    setName(style.name);
    setPrompt(style.style_prompt);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [style?.id]);

  async function save(patch: Partial<Style>) {
    try {
      await stylesApi.update(data.styleId, {
        name: patch.name,
        stylePrompt: patch.style_prompt,
        referenceImages: patch.reference_images,
      });
      data.onUpdate(id, patch);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function onSave() {
    setSaving(true);
    try {
      await save({ name, style_prompt: prompt });
    } finally {
      setSaving(false);
    }
  }

  async function addReference(file: File) {
    if (!style) return;
    setUploading(true);
    try {
      const uploaded = await visuals.upload(file);
      await save({ reference_images: [...style.reference_images, uploaded.path] });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }

  if (!style) {
    return (
      <NodeShell typeLabel="Style" selected={selected} error={Boolean(error)}>
        <div className="node-subtitle">{error ?? 'loading…'}</div>
        <Port id="style:out" type="style" direction="out" label="style" top="calc(100% - 14px)" />
      </NodeShell>
    );
  }

  return (
    <NodeShell typeLabel={`Style · ${style.name}`} selected={selected} error={Boolean(error)} wide>
      <input
        className="node-select"
        value={name}
        onChange={(e) => {
          setName(e.target.value);
          data.onUpdate(id, { name: e.target.value });
        }}
        placeholder="style name"
      />
      <textarea
        className="node-prompt-input"
        rows={2}
        value={prompt}
        placeholder="style prompt, e.g. high-contrast film noir, 35mm grain…"
        onChange={(e) => {
          setPrompt(e.target.value);
          data.onUpdate(id, { style_prompt: e.target.value });
        }}
      />
      <div className="node-controls">
        <button className="node-run-btn" disabled={saving || !dirty} onClick={onSave}>
          {saving ? 'saving…' : dirty ? '● save' : 'saved'}
        </button>
      </div>
      {style.reference_images.length > 0 && (
        <div className="node-subtitle">{style.reference_images.length} reference image(s)</div>
      )}
      {capabilities?.supports_reference_images === false ? (
        <div className="node-subtitle">reference images not supported by the current provider</div>
      ) : (
        <div className="node-controls">
          <label className="node-run-btn" style={{ textAlign: 'center', cursor: 'pointer' }}>
            {uploading ? 'uploading…' : '+ reference image'}
            <input
              type="file"
              accept="image/*"
              style={{ display: 'none' }}
              disabled={uploading}
              onChange={(e) => e.target.files?.[0] && addReference(e.target.files[0])}
            />
          </label>
        </div>
      )}
      {error && <div className="node-error-text">{error}</div>}

      <Port id="style:out" type="style" direction="out" label="style" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
