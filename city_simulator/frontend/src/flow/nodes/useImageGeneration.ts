// Shared by ImageNode and FrameNode -- both are "generate an image and
// attach it to this entity," differing only in what pre-fills the prompt
// and what a required upstream connection is. Kept as one hook so the
// generate -> poll -> attach sequence can't drift between the two.
import { useState } from 'react';
import { city, visuals } from '../../api/client';
import { pollVisualsUntilDone } from '../../api/pollVisuals';
import type { MediaItem } from '../../api/types';

export function useImageGeneration(entityId: string) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate(
    prompt: string,
    tag = '',
    style?: { stylePrompt?: string; styleReferenceImages?: string[] },
  ): Promise<MediaItem | null> {
    setError(null);
    setPending(true);
    try {
      const start = await visuals.generateImage({ prompt, stylePrompt: style?.stylePrompt, styleReferenceImages: style?.styleReferenceImages });
      if (!start.ok) {
        setError(start.error ?? 'failed to start');
        return null;
      }
      const result = await pollVisualsUntilDone();
      if (result.kind !== 'image' || !result.images[0]) {
        setError('generation finished with no image');
        return null;
      }
      const image = result.images[0];
      const saved = await city.addMedia({
        entityId,
        kind: 'image',
        url: image.url,
        localPath: image.local_path,
        prompt,
        tag,
      });
      return saved.media[saved.media.length - 1];
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setPending(false);
    }
  }

  return { pending, error, generate };
}
