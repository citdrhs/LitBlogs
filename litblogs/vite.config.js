import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react-swc'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const appBasePath = env.VITE_APP_BASE_PATH || '/';
  const devApiProxyTarget = env.VITE_DEV_API_PROXY_TARGET || 'https://drhscit.org';

  return {
    base: appBasePath,
    plugins: [react()],
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
