import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

/**
 * Dental Agent web client configuration.
 *
 * - `dev`  (`npm run dev`): Vite dev server on port 3000; every API route is
 *   proxied to the FastAPI backend (default http://127.0.0.1:8000) so the
 *   browser sees a single origin — no CORS involved.
 * - `build` (`npm run build`): static bundle whose assets are emitted with the
 *   ``/app-assets/`` prefix so FastAPI can serve the page at ``/app`` and the
 *   bundle under the same path prefix, again fully same-origin.
 */
export default defineConfig(({ command }) => {
  if (command === 'build') {
    return {
      plugins: [react(), tailwindcss()],
      base: '/app-assets/',
      build: {
        outDir: 'dist',
        emptyOutDir: true,
        // Single-bundle SPA (~500 kB, ~130 kB gzipped); revisit with route-level
        // code splitting if it grows well past this.
        chunkSizeWarningLimit: 650,
      },
    };
  }

  const backendTarget = process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:8000';
  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        '@': path.resolve(import.meta.dirname, '.'),
      },
    },
    server: {
      port: 3000,
      proxy: {
        '/auth': backendTarget,
        '/agent': backendTarget,
        '/feedback': backendTarget,
        '/users': backendTarget,
        '/patients': backendTarget,
        '/doctors': backendTarget,
        '/doctor-schedules': backendTarget,
        '/dental-services': backendTarget,
        '/appointments': backendTarget,
        '/reports': backendTarget,
        '/dev': backendTarget,
        '/health': backendTarget,
      },
    },
  };
});
