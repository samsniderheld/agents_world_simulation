import { useRef, useState } from 'react';
import type { DragEvent } from 'react';
import type { Node, NodeProps } from '@xyflow/react';
import { visuals } from '../../api/client';
import { useLightboxStore } from '../../state/lightboxStore';
import { NodeShell } from './NodeShell';
import { Port } from './Port';

export interface PhotoNodeData extends Record<string, unknown> {
  // The uploaded file (POST /api/visuals/upload, into visuals/data/uploads):
  // `url` for display, `localPath` for whatever it's wired into -- the same
  // pair an Image node keeps for its own result.
  url?: string;
  localPath?: string;
  fileName?: string;
  onUpdate: (nodeId: string, patch: { url?: string; localPath?: string; fileName?: string }) => void;
}

export type PhotoNodeType = Node<PhotoNodeData, 'photo'>;

// A photo from your computer, fed into the graph: wire image:out into an
// Image node (a reference, or the picture to edit) or a Video node (to
// animate it). Choose a file or drop one onto the node.
export function PhotoNode({ id, data, selected }: NodeProps<PhotoNodeType>) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const openLightbox = useLightboxStore((s) => s.open);
  const imageUrl = data.url ? visuals.fileUrl(data.url) : undefined;

  async function upload(file: File | undefined) {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setError(`${file.name} isn't an image`);
      return;
    }
    setError(null);
    setUploading(true);
    try {
      const res = await visuals.upload(file);
      data.onUpdate(id, { url: res.url, localPath: res.path, fileName: file.name });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
    }
  }

  // A file dropped on the node is handled here, not by the canvas (whose
  // own drop handler adds nodes from the drawer).
  function onDrop(e: DragEvent) {
    if (!e.dataTransfer.files.length) return;
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    upload(e.dataTransfer.files[0]);
  }

  return (
    <NodeShell typeLabel="Photo" selected={selected} running={uploading} error={Boolean(error)} minWidth={540} minHeight={380}>
      <div
        className={`node-media-box nodrag ${imageUrl ? 'is-expandable' : ''} ${dragOver ? 'is-drop-target' : ''}`}
        onClick={(e) => {
          e.stopPropagation();
          if (imageUrl) openLightbox(imageUrl);
          else inputRef.current?.click();
        }}
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes('Files')) return;
          e.preventDefault();
          e.stopPropagation();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        {imageUrl ? (
          <img src={imageUrl} alt="" />
        ) : (
          <div className="node-media-box-empty node-photo-empty">{uploading ? 'uploading…' : 'drop a photo here, or click to choose'}</div>
        )}
      </div>
      {data.fileName && <div className="node-subtitle">{data.fileName}</div>}
      {error && <div className="node-error-text">{error}</div>}
      <div className="node-controls">
        <button className="node-run-btn" disabled={uploading} onClick={() => inputRef.current?.click()}>
          {uploading ? 'uploading…' : imageUrl ? '⤒ replace photo' : '⤒ upload photo'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          style={{ display: 'none' }}
          onChange={(e) => {
            upload(e.target.files?.[0]);
            e.target.value = '';
          }}
        />
      </div>

      <Port id="image:out" type="image" direction="out" label="image" top="calc(100% - 14px)" />
    </NodeShell>
  );
}
