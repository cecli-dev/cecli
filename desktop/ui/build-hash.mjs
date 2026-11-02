import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join, relative } from 'node:path';

function collect_files(root) {
  const files = [join(root, 'index.html'), join(root, 'vite.config.js')];

  function walk(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) walk(path);
      else files.push(path);
    }
  }

  for (const directory of ['src', 'public']) {
    if (existsSync(join(root, directory))) walk(join(root, directory));
  }

  for (const name of ['package.json', 'package-lock.json']) {
    const path = join(root, '..', name);
    if (existsSync(path)) files.push(path);
  }

  return files.sort();
}

export function source_hash(root) {
  const digest = createHash('sha256');

  for (const file of collect_files(root)) {
    digest.update(relative(root, file));
    digest.update('\0');
    digest.update(readFileSync(file));
    digest.update('\0');
  }

  return digest.digest('hex');
}

export function build_hash_path(root) {
  return join(root, '..', 'static', '.build-hash');
}