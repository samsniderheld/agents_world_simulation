// visuals/jobs.py is a single global job slot -- only one generation can
// run at a time across the whole app, and starting one while another is
// in flight is rejected outright (see visuals routes' 409 on jobs.start()
// failure). So once a caller's own start request succeeds, no other node
// could have raced in a competing job before this one finishes -- polling
// status/result directly here (rather than through the shared jobStore,
// which exists for cross-scope "is *anything* running" display) is safe
// and simple.
import { visuals } from './client';
import type { VisualsResult } from './types';

const POLL_MS = 1200;

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function pollVisualsUntilDone(): Promise<VisualsResult> {
  for (;;) {
    await sleep(POLL_MS);
    const status = await visuals.status();
    if (status.phase === 'error') throw new Error(status.error ?? 'generation failed');
    if (status.phase === 'done') return visuals.result();
  }
}
