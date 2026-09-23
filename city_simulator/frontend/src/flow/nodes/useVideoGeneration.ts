// Self-contained, like ScratchImageNode/FrameNode -- a generated clip
// belongs to the Video node/treatment it's part of, not to any one
// entity's media history, so this no longer attaches via city.addMedia().
import { useState } from 'react';
import { visuals } from '../../api/client';
import { pollVisualsUntilDone } from '../../api/pollVisuals';

export function useVideoGeneration() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate(prompt: string, imagePath: string, stylePrompt?: string): Promise<{ url: string; localPath: string } | null> {
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
      return { url: result.video.url, localPath: result.video.local_path };
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setPending(false);
    }
  }

  return { pending, error, generate };
}
