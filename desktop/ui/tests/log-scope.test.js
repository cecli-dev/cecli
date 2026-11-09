import assert from 'node:assert/strict';
import test from 'node:test';

import { subscribe_cli_event } from '../src/core/cli-bus.js';
import { handle_event } from '../src/core/events.js';
import {
  clear_terminal_logs,
  get_terminal_logs,
  push_terminal_log,
} from '../src/core/log-bus.js';
import { apply_snapshot } from '../src/core/snapshot.js';
import { create_initial_state } from '../src/core/state.js';
import { Store } from '../src/core/store.js';

test('log entries keep bridge ids, monotonic seq and the 2000 cap', () => {
  clear_terminal_logs();
  push_terminal_log({ message: 'one', bridge_id: 'b1' });
  push_terminal_log({ message: 'two', bridge_id: 'b2' });
  push_terminal_log({ message: 'unscoped' });

  const all = get_terminal_logs();
  assert.equal(all.length, 3);
  assert.ok(all[0].seq < all[2].seq);
  assert.deepEqual(get_terminal_logs('b1').map((entry) => entry.message), ['one', 'unscoped']);

  for (let index = 0; index < 2005; index += 1) push_terminal_log({ message: `line ${index}` });
  assert.equal(get_terminal_logs().length, 2000);
});

test('type:cli events publish to the CLI bus without touching state.logs', () => {
  const store = new Store(create_initial_state());
  store.set_active('b1');
  const seen = [];
  const unsubscribe = subscribe_cli_event((payload) => seen.push(payload));

  handle_event(store, { type: 'cli', bridgeId: 'b1', event: 'started', key: 'bg_1' });

  assert.equal(seen.length, 1);
  assert.equal(seen[0].event, 'started');
  assert.deepEqual(store.state.logs, []);
  unsubscribe();
});

test('snapshots store cliPane and cli additively per bridge', () => {
  const store = new Store(create_initial_state());
  apply_snapshot(store, {
    status: 'ready',
    workspace: '/repo',
    cliPane: { enabled: true, background: true, rawBackground: true, inputLease: true, inputOwner: 'none' },
    cli: { terminals: [], background: [{ key: 'bg_1', state: 'running' }] },
  }, 'b1');

  const state = store.state_for('b1');
  assert.equal(state.cliPane.enabled, true);
  assert.equal(state.cliPane.inputLease, true);
  assert.equal(state.cli.background.length, 1);
  assert.equal(store.state_for('b2').cli.background.length, 0);
});