import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In dev, /api is proxied to the FastAPI server (uv run uvicorn server.app:app --port 8000).
// On Vercel, /api/* is rewritten to the Python function (see ../vercel.json).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://127.0.0.1:8000' } },
  // MapLibre 6 loads its worker as a sibling ESM file; pre-bundling breaks that URL.
  optimizeDeps: { exclude: ['maplibre-gl'] },
})
