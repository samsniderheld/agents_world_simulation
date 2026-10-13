// Self-contained, like an Image node's own result -- a generated clip
// belongs to the Video node/treatment it's part of, not to any one
// entity's media history, so this no longer attaches via city.addMedia().
import { useState } from 'react';
import { visuals } from '../../api/client';
import { pollVisualsUntilDone } from '../../api/pollVisuals';

type Clip = { url: string; localPath: string; seed?: number };

export function useVideoGeneration() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Start a job, then wait for its clip (a reference video takes ~20 minutes).
  async function run(start: () => Promise<{ ok: boolean; error: string | null }>): Promise<Clip | null> {
    setError(null);
    setPending(true);
    try {
      const started = await start();
      if (!started.ok) {
        setError(started.error ?? 'failed to start');
        return null;
      }
      const result = await pollVisualsUntilDone();
      if (result.kind !== 'video' && result.kind !== 'video_reference') {
        setError('generation finished with no video');
        return null;
      }
      return { url: result.video.url, localPath: result.video.local_path, seed: result.seed };
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return null;
    } finally {
      setPending(false);
    }
  }

  // Animate one image (image-to-video).
  function generate(
    prompt: string,
    imagePath: string,
    stylePrompt?: string,
    aspectRatio: string = '16:9',
    provider?: string,
    extraOptions: Record<string, unknown> = {},
    comfyuiUrl?: string,
  ): Promise<Clip | null> {
    return run(() =>
      visuals.generateVideo({ prompt, imagePath, stylePrompt, options: { ...extraOptions, aspect_ratio: aspectRatio }, provider, comfyuiUrl }),
    );
  }

  // A clip from reference pictures (a Storyboard's cast and backgrounds) --
  // ComfyUI's MiniMax H3 reference-to-video workflow.
  function generateFromReferences(
    prompt: string,
    imagePaths: string[],
    aspectRatio: string = '16:9',
    extraOptions: Record<string, unknown> = {},
    comfyuiUrl?: string,
  ): Promise<Clip | null> {
    return run(() =>
      visuals.generateVideoFromReference({
        prompt,
        imagePaths,
        options: { ...extraOptions, aspect_ratio: aspectRatio },
        provider: 'comfyui',
        comfyuiUrl,
      }),
    );
  }

  return { pending, error, setError, generate, generateFromReferences };
}
