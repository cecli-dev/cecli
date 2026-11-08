import assert from 'node:assert/strict';
import test from 'node:test';

import { Session } from '../src/core/session.js';
import { create_initial_state } from '../src/core/state.js';
import { Store } from '../src/core/store.js';

function response(body, ok = true, status = 200) {
  return { ok, status, json: async () => body };
}

function with_fast_timers(callback) {
  const real_raf = globalThis.requestAnimationFrame;
  const real_set_timeout = globalThis.setTimeout;
  globalThis.requestAnimationFrame = (fn) => fn();
  globalThis.setTimeout = (fn) => {
    fn();
    return 0;
  };

  return Promise.resolve()
    .then(callback)
    .finally(() => {
      globalThis.requestAnimationFrame = real_raf;
      globalThis.setTimeout = real_set_timeout;
    });
}

test('send_prompt appends the user turn and marks the session busy', async () => {
  await with_fast_timers(async () => {
    const store = new Store(create_initial_state());
    store.update((state) => ({ ...state, status: 'ready' }));
    const session = new Session(store);
    store.set_sessions([{ bridgeId: 'b1', status: 'ready' }], 8);
    globalThis.fetch = async () => response({ ok: true }, true, 202);

    assert.equal(await session.send_prompt('hello'), true);
    assert.equal(store.state.transcript.length, 1);
    assert.equal(store.state.transcript[0].text, 'hello');
    assert.equal(store.state.busy, true);
    assert.equal(store.state.last_prompt, 'hello');
    assert.equal(store.state.retry_available, false);
  });
});

test('a rejected prompt preserves retry state without adding a turn', async () => {
  await with_fast_timers(async () => {
    const store = new Store(create_initial_state());
    store.update((state) => ({ ...state, status: 'ready' }));
    const session = new Session(store);
    globalThis.fetch = async () => response({ ok: false, error: 'busy' }, false, 409);
    store.set_sessions([{ bridgeId: 'b1', status: 'ready' }], 8);

    assert.equal(await session.send_prompt('hello'), false);
    assert.equal(store.state.transcript.length, 0);
    assert.equal(store.state.busy, false);
    assert.equal(store.state.last_prompt, 'hello');
    assert.equal(store.state.retry_available, true);
  });
});

test('new_chat clears the transcript and session id', async () => {
  await with_fast_timers(async () => {
    const store = new Store(create_initial_state());
    store.update((state) => ({
      ...state,
      status: 'ready',
      workspace: '/tmp/project',
      session_id: 'old',
      transcript: [{ id: 'u', type: 'user', text: 'old' }],
    }));
    const session = new Session(store);
    globalThis.fetch = async () => response({ ok: true }, true, 202);

    await session.new_chat();
    assert.equal(store.state.session_id, null);
    assert.equal(store.state.transcript.length, 0);
    assert.equal(store.state.new_chat_pending, false);
  });
});

test('a workflow run uses the primary transcript', async () => {
  await with_fast_timers(async () => {
    const store = new Store(create_initial_state());
    store.set_sessions([{ bridgeId: 'b1', title: 'one' }], 8);
    store.update((state) => ({
      ...state,
      status: 'ready',
      active_agent_session_id: 'child',
    }));
    const session = new Session(store);
    globalThis.fetch = async () => response({ ok: true }, true, 200);

    await session.registry_action('workflows', 'run', 'demo');

    assert.equal(store.state.active_agent_session_id, null);
    assert.equal(store.state.transcript.length, 1);
    assert.equal(store.state.transcript[0].text, '/workflows run demo');
    assert.equal(store.state.busy, true);
  });
});

test('a rejected workflow leaves no phantom turn', async () => {
  await with_fast_timers(async () => {
    const store = new Store(create_initial_state());
    store.set_sessions([{ bridgeId: 'b1', title: 'one' }], 8);
    store.update((state) => ({ ...state, status: 'ready' }));
    const session = new Session(store);
    globalThis.fetch = async () => response({ ok: false, error: 'busy' }, false, 409);

    await assert.rejects(session.registry_action('workflows', 'run', 'demo'));

    assert.equal(store.state.transcript.length, 0);
    assert.equal(store.state.busy, false);
  });
});