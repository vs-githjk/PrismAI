import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  // ffmpeg.wasm loads an internal Web Worker via import.meta.url. Vite's dep
  // pre-bundling rewrites that into a blob URL the worker can't resolve
  // ("Cannot find module 'blob:...'"), so exclude it and let Vite serve the
  // package source directly.
  optimizeDeps: {
    exclude: ['@ffmpeg/ffmpeg', '@ffmpeg/util'],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return

          if (id.includes('recharts')) {
            return 'charts'
          }

          if (id.includes('@supabase') || id.includes('@supabase/supabase-js')) {
            return 'supabase'
          }

          if (id.includes('react') || id.includes('scheduler')) {
            return 'react-vendor'
          }
        },
      },
    },
  },
})
