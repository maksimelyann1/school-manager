import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    build: {
        rollupOptions: { input: { app: 'index.html', widgets: 'widgets.html' } },
        outDir: 'dist-new',
        emptyOutDir: false,
    },
    server: {
        port: 3000,
        proxy: {
            '/api': {
                target: 'http://localhost:8001',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, '')
            }
        }
    }
})
