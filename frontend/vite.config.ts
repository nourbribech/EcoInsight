import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] })
  ],

  // Every component fetches RELATIVE paths ("/api/current"), never
  // "http://localhost:8000/api/current". In dev this proxy forwards them to
  // the FastAPI process; in production the agent will serve the built assets
  // and the API from the same origin, so the exact same relative paths keep
  // working with no code change and no CORS involved at all.
  //
  // That matches how the product is meant to ship: one background agent the
  // user opens on a localhost port, Netdata-style — not a separate frontend
  // host talking cross-origin to a separate API host.
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
