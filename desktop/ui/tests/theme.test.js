import assert from 'node:assert/strict';
import test from 'node:test';

function install_dom() {
  const classes = new Set();
  const document = {
    body: {
      classList: {
        contains: (name) => classes.has(name),
        toggle: (name, force) => {
          if (force) classes.add(name);
          else classes.delete(name);
        },
      },
      dataset: {},
    },
    documentElement: { style: {} },
    querySelector: () => null,
  };

  const storage = new Map();
  globalThis.document = document;
  globalThis.window = {
    matchMedia: () => ({
      matches: false,
      addEventListener: () => {},
      addListener: () => {},
    }),
  };
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  };
  globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });

  const requests = [];
  globalThis.fetch = async (path, options = {}) => {
    requests.push({ path, options });
    if (path === '/api/theme' && !options.method) {
      return { ok: true, json: async () => ({ ok: true, theme: null }) };
    }
    return { ok: true, json: async () => ({ ok: true }) };
  };

  return { classes, document, requests, storage };
}

test('theme toggles the body class and persists the choice', async () => {
  const dom = install_dom();
  const { get_theme, init_theme, set_theme, subscribe_theme, toggle_theme } = await import(
    '../src/core/theme.js'
  );

  assert.equal(get_theme(), 'light');
  assert.equal(init_theme(), 'light');

  const seen = [];
  const unsubscribe = subscribe_theme((theme) => seen.push(theme));

  assert.equal(toggle_theme(), 'dark');
  assert.equal(dom.classes.has('dark'), true);
  assert.equal(dom.document.body.dataset.theme, 'dark');
  assert.equal(dom.document.documentElement.style.colorScheme, 'dark');
  assert.equal(dom.storage.get('cecli.theme'), 'dark');

  assert.equal(set_theme('light'), 'light');
  assert.equal(dom.classes.has('dark'), false);
  assert.equal(dom.storage.get('cecli.theme'), 'light');

  unsubscribe();
  assert.deepEqual(seen, ['dark', 'light']);

  await new Promise((resolve) => setTimeout(resolve, 0));
  const writes = dom.requests.filter((item) => item.options.method === 'POST');
  assert.deepEqual(
    writes.map((item) => JSON.parse(item.options.body).theme),
    ['dark', 'light'],
  );
});

test('read_theme_color falls back when the variable is unavailable', async () => {
  install_dom();
  const { read_theme_color } = await import('../src/core/theme.js');

  assert.equal(read_theme_color('--missing', '#123456'), '#123456');
});
