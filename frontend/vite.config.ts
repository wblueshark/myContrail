import { fileURLToPath, URL } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The dev server proxies /api to the backend so the browser origin stays
// http://localhost:5173. That origin is on the backend's CORS allowlist, and
// the Host header stays a loopback name, which the backend requires.
export default defineConfig({
  plugins: [react()],
  // The single .env lives at the repository root, not in frontend/. Without
  // this, VITE_MAPBOX_TOKEN is silently undefined and the map renders blank.
  // Only VITE_-prefixed keys are exposed to the client, so DATABASE_URL and the
  // local token in that same file stay out of the bundle.
  envDir: fileURLToPath(new URL('..', import.meta.url)),
  resolve: {
    // Must mirror the "paths" entry in tsconfig.json: tsc resolves @/* on its
    // own, the bundler does not.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          // mapbox-gl and deck.gl dominate the bundle; splitting them keeps the
          // app shell small enough to paint before the map is ready.
          mapbox: ['mapbox-gl'],
          deck: ['@deck.gl/core', '@deck.gl/layers', '@deck.gl/aggregation-layers'],
        },
      },
    },
  },
})
