import { writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

import { build_hash_path, source_hash } from './build-hash.mjs';

const ui_root = dirname(fileURLToPath(import.meta.url));

const stable_asset_plugin = {
  name: 'cecli-stable-assets',
  apply: 'build',
  enforce: 'post',
  transformIndexHtml(html) {
    const version = source_hash(ui_root);
    return html.replace(/(\/static\/assets\/[^"'?]+\.(?:js|css))/g, `$1?v=${version}`);
  },
};

const build_hash = {
  name: 'cecli-build-hash',
  apply: 'build',
  writeBundle() {
    writeFileSync(build_hash_path(ui_root), `${source_hash(ui_root)}\n`);
  },
};

export default defineConfig(({ command, mode }) => ({
  root: ui_root,
  base: command === 'serve' ? '/' : '/static/',
  plugins: [tailwindcss(), ...(mode === 'stable' ? [stable_asset_plugin] : []), build_hash],
  server: {
    proxy: {
      // Keep the browser origin intact so the bridge's Origin/Host check passes.
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
        timeout: 0,
        proxyTimeout: 0,
      },
      '/ws': {
        target: 'ws://127.0.0.1:8765',
        ws: true,
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
    assetsDir: 'assets',
    target: 'es2022',
    ...(mode === 'stable'
      ? {
          rollupOptions: {
            output: {
              entryFileNames: 'assets/index.js',
              chunkFileNames: 'assets/[name].js',
              assetFileNames: 'assets/[name][extname]',
            },
          },
        }
      : {}),
  },
}));
