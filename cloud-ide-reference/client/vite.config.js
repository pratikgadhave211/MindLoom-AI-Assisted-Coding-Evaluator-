import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/agent-api': {
        target: 'http://127.0.0.1:8000',
        ws: true,
        rewrite: path => path.replace(/^\/agent-api/, '')
      },
      '/api': 'http://localhost:3001',
      '/ws': {
        target: 'ws://localhost:3001',
        ws: true
      }
    }
  }
});
