import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// In development the app proxies the API and the panel socket to the Pi (or to a local server).
const server = process.env.FRETCASE_SERVER ?? 'https://localhost:8443'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: server, secure: false },
      '/health': { target: server, secure: false },
      '/ws': { target: server, secure: false, ws: true },
    },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
