import { writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

import { build_hash_path, source_hash } from './build-hash.mjs';

const ui_root = dirname(fileURLToPath(import.meta.url));
const build_hash = {
  name: 'cecli-build-hash',
  apply: 'build',
  writeBundle() {
    writeFileSync(build_hash_path(ui_root), `${source_hash(ui_root)}\n`);
  },
};

export default defineConfig(({ command }) => ({
  root: ui_root,
  base: command === 'serve' ? '/' : '/static/',
  plugins: [tailwindcss(), build_hash],
  server: {
    proxy: {
      // The bridge accepts the Vite origin only because its Origin check compares
      // hostnames, not ports. Changing that check breaks this dev proxy.
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: false,
        timeout: 0,
        proxyTimeout: 0,
      },
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
    assetsDir: 'assets',
    target: 'es2022',
  },
}));
