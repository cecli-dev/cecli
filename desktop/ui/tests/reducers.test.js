import assert from 'node:assert/strict';
import test from 'node:test';

import { handle_event } from '../src/core/events.js';
import { markdown_to_html } from '../src/core/markdown.js';
import { apply_snapshot } from '../src/core/snapshot.js';
import { create_initial_state } from '../src/core/state.js';
import { Store } from '../src/core/store.js';

function create_store() {
  return new Store(create_initial_state());
}

function update(store, session_id, payload) {
  handle_event(store, { type: 'update', sessionId: session_id, update: payload });
}

test('transcript reducers cover every streaming update kind', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1', configOptions: [], modes: {} });

  update(store, 's1', {
    sessionUpdate: 'agent_message_chunk',
    content: { type: 'text', text: 'Hello ' },
  });
  update(store, 's1', {
    sessionUpdate: 'agent_thought_chunk',
    content: { type: 'text', text: 'thinking' },
  });
  update(store, 's1', {
    sessionUpdate: 'agent_message_chunk',
    content: { type: 'text', text: 'world' },
  });
  update(store, 's1', {
    sessionUpdate: 'tool_call',
    toolCallId: 't1',
    title: 'Read file',
    kind: 'read',
    status: 'pending',
  });
  update(store, 's1', {
    sessionUpdate: 'tool_call_update',
    toolCallId: 't1',
    status: 'completed',
  });
  update(store, 's1', {
    sessionUpdate: 'tool_call_content_chunk',
    toolCallId: 't1',
    content: { type: 'text', text: 'file body' },
  });
  update(store, 's1', {
    sessionUpdate: 'plan',
    entries: [{ content: 'Inspect', status: 'completed' }],
  });
  update(store, 's1', { sessionUpdate: 'usage_update', used: 10, size: 100 });

  assert.equal(store.state.transcript.length, 2);
  const first = store.state.transcript[0];
  assert.deepEqual(first.parts.map((part) => part.type), ['text']);
  assert.equal(first.parts[0].text, 'Hello ');

  const turn = store.state.transcript[1];
  assert.deepEqual(
    turn.parts.map((part) => part.type),
    ['thought', 'text', 'tool', 'plan'],
  );
  assert.equal(turn.parts[0].text, 'thinking');
  assert.equal(turn.parts[1].text, 'world');
  assert.equal(turn.parts[2].content_text, 'file body');
  assert.equal(turn.parts[2].status, 'completed');
  assert.equal(turn.parts[3].entries.length, 1);
});

test('permissions resolve and clear with the turn', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });
  handle_event(store, {
    type: 'permission',
    requestId: 7,
    sessionId: 's1',
    toolCall: { content: [{ type: 'content', content: { type: 'text', text: 'run' } }] },
    options: [{ optionId: 'y', name: 'Yes' }],
  });

  assert.equal(store.state.permissions.length, 1);
  assert.equal(store.state.busy, true);
  assert.equal(store.state.turn_state, 'requires_action');

  handle_event(store, { type: 'permission_resolved', requestId: 7, optionId: 'y' });
  assert.equal(store.state.permissions[0].resolved, true);
  assert.equal(store.state.permissions[0].chosen, 'y');

  handle_event(store, { type: 'prompt_done', stopReason: 'end_turn' });
  assert.equal(store.state.permissions.length, 0);
  assert.equal(store.state.busy, false);
  assert.equal(store.state.turn_state, 'idle');
});

test('stale session updates are ignored', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 'new' });
  update(store, 'old', {
    sessionUpdate: 'agent_message_chunk',
    content: { type: 'text', text: 'stale' },
  });

  assert.equal(store.state.transcript.length, 0);
});

test('snapshots restore session, workspace, and permissions', () => {
  const store = create_store();
  apply_snapshot(store, {
    status: 'ready',
    busy: true,
    workspace: '/tmp/project',
    sessionId: 's9',
    configOptions: [],
    modes: {},
    agent: { name: 'cecli', version: '1' },
    permissions: [{ requestId: 3, sessionId: 's9', toolCall: {}, options: [] }],
  });

  assert.equal(store.state.workspace, '/tmp/project');
  assert.equal(store.state.session_id, 's9');
  assert.equal(store.state.permissions.length, 1);
  assert.equal(store.state.busy, true);
});

test('markdown escapes HTML before formatting', () => {
  const html = markdown_to_html('**bold** <script>alert(1)</script>');
  assert.match(html, /<strong>bold<\/strong>/);
  assert.ok(!html.includes('<script'));
  assert.match(html, /&lt;script&gt;/);
});

test('assistant message blocks break on new streams and context messages', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });

  update(store, 's1', {
    sessionUpdate: 'agent_message_chunk',
    content: { type: 'text', text: 'answer one' },
  });
  update(store, 's1', {
    sessionUpdate: 'agent_thought_chunk',
    content: { type: 'text', text: 'thinking two' },
  });
  update(store, 's1', {
    sessionUpdate: 'agent_message_chunk',
    content: { type: 'text', text: 'answer two' },
  });
  update(store, 's1', {
    sessionUpdate: 'tool_call',
    toolCallId: 't2',
    title: 'Read file',
    kind: 'read',
    status: 'pending',
  });

  update(store, 's1', {
    sessionUpdate: 'session_message',
    senderSessionId: 'child',
    recipientSessionId: 's1',
    content: [{ type: 'text', text: 'child note' }],
  });
  update(store, 's1', {
    sessionUpdate: 'agent_thought_chunk',
    content: { type: 'text', text: 'thinking three' },
  });
  update(store, 's1', {
    sessionUpdate: 'agent_message_chunk',
    content: { type: 'text', text: 'answer three' },
  });
  update(store, 's1', {
    sessionUpdate: 'tool_call_update',
    toolCallId: 't2',
    status: 'completed',
  });

  assert.deepEqual(
    store.state.transcript.map((item) => item.type),
    ['assistant', 'assistant', 'context', 'assistant'],
  );
  assert.deepEqual(
    store.state.transcript[0].parts.map((part) => part.type),
    ['text'],
  );
  assert.deepEqual(
    store.state.transcript[1].parts.map((part) => part.type),
    ['thought', 'text', 'tool'],
  );
  assert.deepEqual(
    store.state.transcript[3].parts.map((part) => part.type),
    ['thought', 'text'],
  );
  assert.equal(store.state.transcript[1].parts[2].status, 'completed');
  assert.equal(store.state.transcript[1].parts[0].open, false);
  assert.equal(store.state.transcript[1].parts[0].auto_open, false);
});

test('primary activity follows state updates back to idle', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });

  update(store, 's1', { sessionUpdate: 'state_update', state: 'running' });
  assert.equal(store.state.activity, 'running');
  assert.equal(store.state.busy, true);

  update(store, 's1', { sessionUpdate: 'state_update', state: 'idle' });
  assert.equal(store.state.activity, 'idle');
  assert.equal(store.state.busy, false);
  assert.equal(store.state.turn_state, 'idle');
});