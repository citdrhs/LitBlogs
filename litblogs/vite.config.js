import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'

// https://vite.dev/config/
export default defineConfig({
  base: '/dren/'
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'https://drhscit.org/dren',
    },
  },
})
