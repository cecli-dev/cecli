import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { build_hash_path, source_hash } from '../ui/build-hash.mjs';

const ui_root = join(dirname(fileURLToPath(import.meta.url)), '..', 'ui');
const expected = source_hash(ui_root);
const path = build_hash_path(ui_root);

let actual = '';
try {
  actual = readFileSync(path, 'utf8').trim();
} catch (error) {
  console.error('static/ has no build hash; run `npm run ui:build`');
  process.exit(1);
}

if (actual !== expected) {
  console.error('static/ is stale; run `npm run ui:build` and commit the output');
  process.exit(1);
}

const static_root = join(ui_root, '..', 'static');
const index_path = join(static_root, 'index.html');

if (!existsSync(index_path)) {
  console.error('static/index.html is missing; run `npm run ui:build`');
  process.exit(1);
}

const page = readFileSync(index_path, 'utf8');
for (const match of page.matchAll(/\/static\/(assets\/[^"']+)/g)) {
  if (!existsSync(join(static_root, match[1]))) {
    console.error(`static/${match[1]} is missing; run \`npm run ui:build\``);
    process.exit(1);
  }
}

console.log('static/ matches the current ui/ sources');