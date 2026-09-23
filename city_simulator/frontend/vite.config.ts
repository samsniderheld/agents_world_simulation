import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Built assets are served by Flask straight out of city_simulator/static/,
// so base+outDir line up with how app.py resolves them -- see app.py's
// index()/catch-all routes. `base` only applies to the production build
// (command === 'build'): the dev server needs to stay rooted at / so
// `npm run dev` serves the app directly, not under /static/dist/.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/static/dist/' : '/',
  build: {
    outDir: '../static/dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      // Dev-mode only: lets `npm run dev` talk to the real Flask process
      // on :8420 without needing flask-cors -- production serves both
      // from the same Flask origin, where this is moot.
      '/api': 'http://127.0.0.1:8420',
    },
  },
}))
