
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],

  server: {
    host: '127.0.0.1',
    port: 5173,

    proxy: {
      '/clinical': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },

      '/auth': 'http://127.0.0.1:8000',
      '/my': 'http://127.0.0.1:8000',
      '/doctors': 'http://127.0.0.1:8000',
      '/doctor': 'http://127.0.0.1:8000',
      '/appointments': 'http://127.0.0.1:8000',
      '/patients': 'http://127.0.0.1:8000',
      '/queries': 'http://127.0.0.1:8000',

      // Patient AI Assistant — Groq backend
      '/patient/ai': 'http://127.0.0.1:8000',
    },
  },
})
