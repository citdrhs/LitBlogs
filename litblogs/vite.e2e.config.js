import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';

const backendUrl = process.env.E2E_BACKEND_URL || 'http://127.0.0.1:8001';
const buildDirectory = process.env.E2E_BUILD_DIR || 'dist-e2e';

export default defineConfig({
  base: '/',
  plugins: [react()],
  build: {
    outDir: buildDirectory,
    emptyOutDir: true,
  },
  preview: {
    host: '127.0.0.1',
    port: Number.parseInt(process.env.E2E_FRONTEND_PORT || '4173', 10),
    strictPort: true,
    proxy: {
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
    },
  },
});
