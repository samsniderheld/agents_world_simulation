// Mirrors useImageGeneration.ts but for video -- kept separate rather
// than a shared generic, since the request shape (image_path is required
// here, sourced from an upstream Frame node, not a free-form list) and
// result shape (`video`, not `images[]`) genuinely differ.
import { useState } from 'react';
import { city, visuals } from '../../api/client';
import { pollVisualsUntilDone } from '../../api/pollVisuals';
import type { MediaItem } from '../../api/types';

export function useVideoGeneration(entityId: string) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate(prompt: string, imagePath: string, stylePrompt?: string): Promise<MediaItem | null> {
    setError(null);
    setPending(true);
    try {
      const start = await visuals.generateVideo({ prompt, imagePath, stylePrompt });
      if (!start.ok) {
        setError(start.error ?? 'failed to start');
        return null;
      }
      const result = await pollVisualsUntilDone();
      if (result.kind !== 'video' && result.kind !== 'video_reference') {
        setError('generation finished with no video');
        return null;
      }
      const video = result.video;
      const saved = await city.addMedia({
        entityId,
        kind: 'video',
        url: video.url,
        localPath: video.local_path,
        prompt,
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
