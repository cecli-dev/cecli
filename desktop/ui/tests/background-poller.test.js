import assert from 'node:assert/strict';
import test from 'node:test';

import { BackgroundPoller, POLL_COLLAPSED_MS, POLL_VISIBLE_MS } from '../src/core/background-poller.js';

test('visible and collapsed intervals differ', () => {
  let collapsed = false;
  let delay = null;
  const poller = new BackgroundPoller({
    fetch_state: async () => ({ background: [] }),
    on_state: () => {},
    is_collapsed: () => collapsed,
  });

  const original = globalThis.setTimeout;
  globalThis.setTimeout = (fn, value) => { delay = value; return 1; };
  poller.set_bridge('b1');
  assert.equal(delay, POLL_VISIBLE_MS);

  collapsed = true;
  poller.schedule();
  assert.equal(delay, POLL_COLLAPSED_MS);
  poller.stop();
  globalThis.setTimeout = original;
});

test('a stale bridge response is ignored', async () => {
  const seen = [];
  let release = null;
  const poller = new BackgroundPoller({
    fetch_state: (bridge) => new Promise((resolve) => { release = () => resolve({ bridge, background: [] }); }),
    on_state: (result) => seen.push(result),
  });

  poller.set_bridge('b1');
  const tick = poller.tick();
  poller.set_bridge('b2');
  release();
  await tick;

  assert.deepEqual(seen, []);
  poller.stop();
});

test('404 marks background unsupported and stops polling', async () => {
  let calls = 0;
  const errors = [];
  const poller = new BackgroundPoller({
    fetch_state: async () => { calls += 1; throw Object.assign(new Error('missing'), { status: 404 }); },
    on_state: () => {},
    on_error: (error) => errors.push(error),
  });

  poller.set_bridge('b1');
  await poller.tick();

  assert.equal(calls, 1);
  assert.equal(poller.supported, false);
  assert.equal(errors.length, 1);
  poller.stop();
});

test('overlapping ticks do not issue a second request', async () => {
  let calls = 0;
  const poller = new BackgroundPoller({
    fetch_state: async () => { calls += 1; return { background: [] }; },
    on_state: () => {},
  });

  poller.set_bridge('b1');
  await Promise.all([poller.tick(), poller.tick()]);
  assert.equal(calls, 1);
  poller.stop();
});