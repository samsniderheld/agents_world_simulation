// One shared poll loop for all three async job kinds (history generation,
// agent runs, visuals generation), started once at the app root rather
// than per-route -- this is what lets a running job keep showing as
// running while you navigate the canvas (drill into a city, back out,
// etc.), which per-page polling couldn't do.
import { create } from 'zustand';
import { agentsApi, history, visuals } from '../api/client';
import type { AgentsState, JobStatus } from '../api/types';

interface JobState {
  historyStatus: JobStatus | null;
  agentsState: AgentsState | null;
  visualsStatus: JobStatus | null;
  polling: boolean;
  start: () => void;
  stop: () => void;
}

const POLL_MS = 1500;
let intervalId: ReturnType<typeof setInterval> | null = null;

export const useJobStore = create<JobState>((set, get) => ({
  historyStatus: null,
  agentsState: null,
  visualsStatus: null,
  polling: false,

  start: () => {
    if (get().polling) return;
    set({ polling: true });

    const tick = async () => {
      const [historyStatus, agentsState, visualsStatus] = await Promise.all([
        history.status().catch(() => null),
        agentsApi.state().catch(() => null),
        visuals.status().catch(() => null),
      ]);
      set({ historyStatus, agentsState, visualsStatus });
    };

    tick();
    intervalId = setInterval(tick, POLL_MS);
  },

  stop: () => {
    if (intervalId) clearInterval(intervalId);
    intervalId = null;
    set({ polling: false });
  },
}));
