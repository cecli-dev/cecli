import assert from 'node:assert/strict';
import test from 'node:test';

import { resolve_terminal_state_event, terminal_state_event } from '../src/core/terminal-state.js';

const terminals = [{ id: 'term:s1:1' }];

test('terminal state events carry their bridge', () => {
  assert.deepEqual(terminal_state_event('s1', terminals), {
    bridge_id: 's1',
    terminals,
  });
});

test('terminal state events default to an empty list', () => {
  assert.deepEqual(terminal_state_event('s1', null), { bridge_id: 's1', terminals: [] });
});

test('a branded detail keeps its own bridge over the active fallback', () => {
  assert.deepEqual(
    resolve_terminal_state_event({ bridge_id: 's1', terminals }, 's2'),
    { bridge_id: 's1', terminals },
  );
});

test('camel-case details are accepted', () => {
  assert.deepEqual(
    resolve_terminal_state_event({ bridgeId: 's1', terminals }, 's2'),
    { bridge_id: 's1', terminals },
  );
});

test('legacy array details fall back to the active bridge', () => {
  assert.deepEqual(resolve_terminal_state_event(terminals, 's2'), {
    bridge_id: 's2',
    terminals,
  });
});

test('missing or malformed details are ignored', () => {
  assert.equal(resolve_terminal_state_event(null, 's2'), null);
  assert.equal(resolve_terminal_state_event({ terminals }, 's2'), null);
  assert.equal(resolve_terminal_state_event([], ''), null);
});
