import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: '127.0.0.1',
    port: 5174,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8766' },
  },
  build: { outDir: 'dist' },
});
