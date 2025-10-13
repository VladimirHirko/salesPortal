// vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    strictPort: true,
    proxy: {
      '/api': {
        // было: target: 'http://127.0.0.1:8001'
        target: 'http://localhost:8001',
        changeOrigin: true,
        secure: false,
        // можно оставить, но уже не критично:
        cookieDomainRewrite: 'localhost',
      },
    },
  },
})
