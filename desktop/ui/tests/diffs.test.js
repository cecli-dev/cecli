import assert from 'node:assert/strict';
import test from 'node:test';

import { handle_event } from '../src/core/events.js';
import { diff_lines, is_pill_part } from '../src/core/format.js';
import { apply_history } from '../src/core/history.js';
import { create_initial_state } from '../src/core/state.js';
import { Store } from '../src/core/store.js';

const DIFF = '@@ -1 +1 @@\n-old line\n+new line';
const OTHER_DIFF = '@@ -3 +3 @@\n-before\n+after';

function create_store() {
  return new Store(create_initial_state());
}

function update(store, session_id, payload) {
  handle_event(store, { type: 'update', sessionId: session_id, update: payload });
}

function diff_parts(items) {
  return items.flatMap((item) => (item.parts || []).filter((part) => part.type === 'diff'));
}

test('a diff update adds a completed pill part to the main transcript', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });

  update(store, 's1', { sessionUpdate: 'diff', filePath: 'src/a.js', diff: DIFF });

  assert.equal(store.state.transcript.length, 1);
  const parts = store.state.transcript[0].parts;
  assert.deepEqual(parts.map((part) => part.type), ['diff']);
  assert.equal(parts[0].file, 'src/a.js');
  assert.equal(parts[0].diff, DIFF);
  assert.equal(parts[0].status, 'completed');
});

test('a sub-agent diff lands only in that sub-agent transcript', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });
  handle_event(store, { type: 'subagents', subagents: [{ sessionId: 'child-1' }] });

  update(store, 'child-1', { sessionUpdate: 'diff', filePath: 'src/b.js', diff: DIFF });

  assert.equal(store.state.transcript.length, 0);
  const child = store.state.subagent_transcripts['child-1'];
  assert.equal(child.length, 1);
  assert.equal(child[0].parts[0].type, 'diff');
  assert.equal(child[0].parts[0].file, 'src/b.js');
});

test('duplicate diff updates dedupe but new content for a file is kept', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });

  update(store, 's1', { sessionUpdate: 'diff', filePath: 'src/a.js', diff: DIFF });
  update(store, 's1', { sessionUpdate: 'diff', filePath: 'src/a.js', diff: DIFF });
  assert.equal(diff_parts(store.state.transcript).length, 1);

  update(store, 's1', { sessionUpdate: 'diff', filePath: 'src/a.js', diff: OTHER_DIFF });
  assert.equal(diff_parts(store.state.transcript).length, 2);
});

test('history replay attaches diffs to the right session without duplicates', () => {
  const store = create_store();
  store.set_active('bridge');
  const payload = {
    messages: [
      { role: 'user', content: 'hi' },
      { role: 'assistant', content: 'ok' },
    ],
    diffs: [{ file: 'src/a.js', diff: DIFF }],
    subagents: [
      {
        sessionId: 'child',
        messages: [
          { role: 'user', content: 'work' },
          { role: 'assistant', content: 'done' },
        ],
        diffs: [{ file: 'src/b.js', diff: OTHER_DIFF }],
      },
    ],
  };

  apply_history(store, payload, 'bridge');
  apply_history(store, payload, 'bridge');

  const state = store.state_for('bridge');
  const main_parts = diff_parts(state.transcript);
  assert.equal(main_parts.length, 1);
  assert.equal(main_parts[0].file, 'src/a.js');
  assert.equal(main_parts[0].diff, DIFF);

  const child_parts = diff_parts(state.subagent_transcripts.child);
  assert.equal(child_parts.length, 1);
  assert.equal(child_parts[0].file, 'src/b.js');
  assert.equal(child_parts[0].diff, OTHER_DIFF);
});

test('pill classification and diff line rendering helpers are pure', () => {
  assert.equal(is_pill_part({ type: 'diff' }), true);
  assert.equal(is_pill_part({ type: 'thought' }), true);
  assert.equal(is_pill_part({ type: 'tool' }), true);
  assert.equal(is_pill_part({ type: 'text' }), false);
  assert.equal(is_pill_part({ type: 'plan' }), false);
  assert.equal(is_pill_part(null), false);

  assert.deepEqual(
    diff_lines('@@ -1 +1 @@\n--- a\n+++ b\n-old\n+new\n context').map((line) => line.kind),
    ['hunk', 'hunk', 'hunk', 'del', 'add', 'ctx'],
  );
});
