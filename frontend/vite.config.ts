import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const apiProxyTarget = process.env.DOCKWATCH_API_PROXY_TARGET ?? 'http://localhost:8080'
const wsProxyTarget = process.env.DOCKWATCH_WS_PROXY_TARGET ?? apiProxyTarget.replace(/^http/, 'ws')

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
      '/ws': { target: wsProxyTarget, ws: true },
    },
  },
})
