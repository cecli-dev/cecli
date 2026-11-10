#!/usr/bin/env node

import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const tauri = join(root, 'node_modules', '@tauri-apps', 'cli', 'tauri.js');

const env = { ...process.env };

if (supports_system_ca(process.versions.node)) {
  env.NODE_OPTIONS = append_node_option(env.NODE_OPTIONS, '--use-system-ca');
}

if (is_wsl()) {
  env.WEBKIT_DISABLE_DMABUF_RENDERER = '1';
  env.WEBKIT_DISABLE_COMPOSITING_MODE = '1';
}

const child = spawn(process.execPath, [tauri, ...process.argv.slice(2)], {
  cwd: root,
  env,
  stdio: 'inherit',
});

child.on('error', (error) => {
  console.error(`failed to start the Tauri CLI: ${error.message}`);
  process.exitCode = 1;
});

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
  process.on(signal, () => child.kill(signal));
}

child.on('exit', (code, signal) => {
  if (signal) {
    process.removeAllListeners(signal);
    process.kill(process.pid, signal);
    return;
  }

  process.exitCode = code ?? 1;
});

function supports_system_ca(version) {
  const [major, minor] = version.split('.').map(Number);

  if (major >= 24) return true;
  if (major === 23) return minor >= 9;
  if (major === 22) return minor >= 15;

  return false;
}

function append_node_option(existing, option) {
  const options = existing?.trim();

  if (!options) return option;
  if (options.split(/\s+/).includes(option)) return options;

  return `${options} ${option}`;
}

function is_wsl() {
  if (process.platform !== 'linux') return false;
  if (process.env.WSL_DISTRO_NAME || process.env.WSL_INTEROP) return true;

  try {
    return /microsoft|wsl/i.test(readFileSync('/proc/sys/kernel/osrelease', 'utf8'));
  } catch {
    return false;
  }
}