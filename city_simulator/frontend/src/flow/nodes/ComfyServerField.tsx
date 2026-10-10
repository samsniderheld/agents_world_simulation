import { useState } from 'react';
import { visuals } from '../../api/client';
import type { ComfyCheck, VisualsProviders } from '../../api/types';
import { refreshVisualsProviders } from './useProviderCapabilities';

// A ComfyUI node's own server address (an Image or Video node using ComfyUI).
// Blank = the default for its kind; "test" checks the server is up with the
// workflow's nodes and models; "make default" makes this address every
// node's default (saved on the server, so it survives restarts).
export function ComfyServerField({
  kind,
  value,
  info,
  onChange,
}: {
  kind: 'image' | 'video';
  value: string;
  info: VisualsProviders | null;
  onChange: (url: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  const [shown, setShown] = useState(value);
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  if (value !== shown) {
    setShown(value);
    setDraft(value);
  }
  const fallback = info?.comfyui_urls?.[kind];

  async function test() {
    setBusy(true);
    setStatus(null);
    try {
      setStatus(describe(await visuals.comfyuiCheck(kind, draft.trim())));
    } catch (e) {
      setStatus({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  async function makeDefault() {
    setBusy(true);
    try {
      const res = await visuals.comfyuiSetDefault(kind, draft.trim());
      if (!res.ok) setStatus({ ok: false, text: res.error ?? 'failed' });
      else {
        setStatus({ ok: true, text: `now the default ${kind} server` });
        refreshVisualsProviders();
      }
    } catch (e) {
      setStatus({ ok: false, text: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="node-comfy-server nodrag">
      <div className="node-controls">
        <input
          className="node-select node-comfy-url"
          value={draft}
          placeholder={fallback ? `ComfyUI: default (${fallback.replace(/^https?:\/\//, '')})` : 'ComfyUI URL'}
          title="This node's ComfyUI address, e.g. https://<pod id>-8188.proxy.runpod.net -- blank uses the default"
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => draft.trim() !== value && onChange(draft.trim())}
          onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
        />
        <button className="node-link-btn" disabled={busy} onClick={test}>
          test
        </button>
        {draft.trim() && draft.trim().replace(/\/+$/, '') !== fallback && (
          <button className="node-link-btn" disabled={busy} onClick={makeDefault} title={`Use this address for every ${kind} node without its own`}>
            make default
          </button>
        )}
      </div>
      {(busy || status) && (
        <div className={`node-subtitle ${status && !status.ok ? 'node-error-text' : ''}`}>{busy ? 'checking…' : status?.text}</div>
      )}
    </div>
  );
}

function describe(c: ComfyCheck): { ok: boolean; text: string } {
  if (c.error) return { ok: false, text: c.error };
  const who = [c.version && `ComfyUI ${c.version}`, c.gpu].filter(Boolean).join(' · ');
  if (c.ok) return { ok: true, text: `✓ ${who} -- ready` };
  const problems = [
    c.missing_nodes?.length ? `missing nodes: ${c.missing_nodes.join(', ')}` : '',
    c.missing_models?.length ? `missing models: ${c.missing_models.join(', ')}` : '',
  ].filter(Boolean);
  return { ok: false, text: `${who}: ${problems.join('; ')}` };
}
