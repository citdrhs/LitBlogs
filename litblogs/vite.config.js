import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react-swc'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const appBasePath = env.VITE_APP_BASE_PATH || '/';
  const devApiProxyTarget = env.VITE_DEV_API_PROXY_TARGET || 'http://127.0.0.1:8000';

  return {
    base: appBasePath,
    plugins: [react()],
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.js',
    },
    server: {
      proxy: {
        '/api': {
          target: devApiProxyTarget,
          changeOrigin: true,
        },
        '/uploads': {
          target: devApiProxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
})
