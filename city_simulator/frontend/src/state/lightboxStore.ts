// One global "expanded image" overlay, mounted once at the app root
// (App.tsx) -- every node thumbnail and Inspector media item opens the
// same instance rather than each owning its own modal state, so there's
// only ever one lightbox open at a time no matter which screen it's
// triggered from.
import { create } from 'zustand';

interface LightboxState {
  url: string | null;
  open: (url: string) => void;
  close: () => void;
}

export const useLightboxStore = create<LightboxState>((set) => ({
  url: null,
  open: (url) => set({ url }),
  close: () => set({ url: null }),
}));
