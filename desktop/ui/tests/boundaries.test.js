import assert from 'node:assert/strict';
import test from 'node:test';

import { handle_event } from '../src/core/events.js';
import { apply_history } from '../src/core/history.js';
import { apply_snapshot } from '../src/core/snapshot.js';
import { create_initial_state } from '../src/core/state.js';
import { Store } from '../src/core/store.js';

function create_store() {
  return new Store(create_initial_state());
}

function permission(store, request_id, session_id = 'live') {
  handle_event(store, {
    type: 'permission',
    requestId: request_id,
    sessionId: session_id,
    toolCall: {},
    options: [{ optionId: 'y', name: 'Yes' }],
  });
}

test('updates before a session is adopted are dropped', () => {
  const store = create_store();

  handle_event(store, {
    type: 'update',
    sessionId: 'stale',
    update: {
      sessionUpdate: 'agent_message_chunk',
      content: { type: 'text', text: 'old' },
    },
  });
  assert.equal(store.state.transcript.length, 0);

  handle_event(store, { type: 'session', sessionId: 'live' });
  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'agent_message_chunk',
      content: { type: 'text', text: 'new' },
    },
  });
  assert.equal(store.state.transcript.length, 1);
  assert.equal(store.state.transcript[0].parts[0].text, 'new');
});

test('permission cards for another session are ignored', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 'live' });

  permission(store, 1, 'stale');
  assert.equal(store.state.permissions.length, 0);

  permission(store, 2, 'live');
  assert.equal(store.state.permissions.length, 1);
});

test('resolving one permission keeps the other pending cards', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });
  permission(store, 1, 's1');
  permission(store, 2, 's1');

  handle_event(store, { type: 'permission_resolved', requestId: 1, optionId: 'y' });

  assert.equal(store.state.permissions.length, 2);
  assert.equal(store.state.permissions.find((item) => item.key === '1').resolved, true);
  assert.equal(store.state.permissions.find((item) => item.key === '2').resolved, false);
  assert.equal(store.state.turn_state, 'requires_action');
  assert.equal(store.state.busy, true);
});

test('a snapshot during a stop keeps the stopping state', () => {
  const store = create_store();
  store.update((state) => ({
    ...state,
    busy: true,
    stopping: true,
    turn_state: 'running',
    session_id: 's1',
  }));

  apply_snapshot(store, {
    status: 'ready',
    busy: true,
    sessionId: 's1',
    workspace: '/tmp/project',
    configOptions: [],
    modes: {},
    agent: { name: 'cecli', version: '1' },
    permissions: [],
  });

  assert.equal(store.state.stopping, true);
  assert.equal(store.state.busy_message, 'Stopping…');
});

test('a snapshot drops permission cards the bridge no longer lists', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });
  permission(store, 1, 's1');
  permission(store, 2, 's1');

  apply_snapshot(store, {
    status: 'ready',
    busy: true,
    sessionId: 's1',
    configOptions: [],
    modes: {},
    permissions: [{ requestId: 2, sessionId: 's1', toolCall: {}, options: [] }],
  });

  assert.equal(store.state.permissions.length, 1);
  assert.equal(store.state.permissions[0].key, '2');
});
test('a snapshot that prunes every card returns the turn to running', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 's1' });
  permission(store, 1, 's1');
  assert.equal(store.state.turn_state, 'requires_action');

  apply_snapshot(store, {
    status: 'ready',
    busy: true,
    sessionId: 's1',
    configOptions: [],
    modes: {},
    permissions: [],
  });

  assert.equal(store.state.permissions.length, 0);
  assert.equal(store.state.turn_state, 'running');
  assert.equal(store.state.busy_message, 'cecli is working…');
});

test('a session message for a sub-agent lands in its transcript', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 'live' });
  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'subagent_update',
      sessionId: 'child',
      title: 'worker',
      capabilities: {},
      state: { state: 'running' },
    },
  });

  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'session_message',
      senderSessionId: 'live',
      recipientSessionId: 'child',
      userMessage: true,
      content: [{ type: 'text', text: 'hello child' }],
    },
  });

  assert.equal(store.state.transcript.length, 0);
  assert.equal(store.state.subagent_transcripts.child.length, 1);
  assert.equal(store.state.subagent_transcripts.child[0].type, 'user');
  assert.equal(store.state.subagent_transcripts.child[0].text, 'hello child');
});

test('a subagent update patches the sidebar summary', () => {
  const store = create_store();
  store.set_sessions([{ bridgeId: 'b1', title: 'one', subagents: [] }], 8);
  handle_event(store, { type: 'session', sessionId: 'live' });

  handle_event(store.scoped('b1'), {
    type: 'update',
    bridgeId: 'b1',
    sessionId: 'live',
    update: {
      sessionUpdate: 'subagent_update',
      sessionId: 'child',
      title: 'worker',
      capabilities: {},
      state: { state: 'running' },
    },
  });

  assert.equal(store.sessions[0].subagents.length, 1);
  assert.equal(store.sessions[0].subagents[0].title, 'worker');
});

test('agent messages land once in each transcript', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 'live' });
  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'subagent_update',
      sessionId: 'child',
      title: 'worker',
      capabilities: {},
      state: { state: 'running' },
    },
  });

  const message = {
    sessionUpdate: 'session_message',
    senderSessionId: 'child',
    recipientSessionId: 'live',
    content: [{ type: 'text', text: 'from child' }],
  };
  handle_event(store, { type: 'update', sessionId: 'child', update: message });
  handle_event(store, { type: 'update', sessionId: 'live', update: message });

  assert.equal(store.state.subagent_transcripts.child.length, 1);
  assert.equal(store.state.subagent_transcripts.child[0].type, 'context');
  assert.equal(store.state.transcript.length, 1);
  assert.equal(store.state.transcript[0].text, 'from child');
  assert.equal(store.state.transcript[0].type, 'context');
});

test('removing the selected sub-agent returns to the primary', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 'live' });
  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'subagent_update',
      sessionId: 'child',
      title: 'worker',
      capabilities: {},
      state: { state: 'running' },
    },
  });
  store.update((state) => ({ ...state, active_agent_session_id: 'child' }));

  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: { sessionUpdate: 'subagent_update', sessionId: 'child', capabilities: null },
  });

  assert.equal(store.state.active_agent_session_id, null);
});

test('wrapped user input becomes a user bubble but plain context does not', () => {
  const store = create_store();
  handle_event(store, { type: 'session', sessionId: 'live' });
  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'subagent_update',
      sessionId: 'child',
      title: 'worker',
      capabilities: {},
      state: { state: 'running' },
    },
  });
  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'session_message',
      senderSessionId: 'child',
      recipientSessionId: 'live',
      content: [
        {
          type: 'text',
          text: '<context name="user_input" from="agent">\nreal prompt\n</context>',
        },
      ],
    },
  });
  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'session_message',
      senderSessionId: 'child',
      recipientSessionId: 'live',
      content: [{ type: 'text', text: 'tool result' }],
    },
  });

  assert.equal(store.state.transcript[0].type, 'user');
  assert.equal(store.state.transcript[0].text, 'real prompt');
  assert.equal(store.state.transcript[1].type, 'context');
  assert.equal(store.state.transcript[1].text, 'tool result');
  assert.equal(store.state.transcript[1].title, 'Agent message');
  assert.equal(store.state.transcript[1].source, 'worker');

  handle_event(store, {
    type: 'update',
    sessionId: 'live',
    update: {
      sessionUpdate: 'session_message',
      senderSessionId: 'child',
      recipientSessionId: 'live',
      content: [
        {
          type: 'text',
          text: '<context name="sub_agent_result" from="agent">\nresult body\n</context >',
        },
      ],
    },
  });

  const message = store.state.transcript[2];
  assert.equal(message.type, 'context');
  assert.equal(message.text, 'result body');
  assert.equal(message.title, 'Sub agent result');
  assert.equal(message.source, 'worker');
});

test('history replay builds ordered user, assistant and tool turns', () => {
  const store = create_store();
  store.set_active('bridge');

  apply_history(
    store,
    {
      messages: [
        {
          role: 'user',
          content: '<context name="user_input" from="agent">\nHello there\n</context>',
        },
        { role: 'assistant', content: 'Hi, I can help.' },
        {
          role: 'assistant',
          content: '',
          toolCalls: [{ id: 'call-1', name: 'ReadFile', arguments: '{"path":"a"}' }],
        },
        { role: 'tool', toolCallId: 'call-1', content: 'file body' },
        { role: 'assistant', content: 'All done.' },
      ],
      subagents: [
        {
          sessionId: 'child',
          messages: [
            { role: 'user', content: 'work' },
            { role: 'assistant', content: 'child reply' },
          ],
        },
      ],
    },
    'bridge',
  );

  const state = store.state_for('bridge');
  assert.equal(state.transcript[0].type, 'user');
  assert.equal(state.transcript[0].text, 'Hello there');
  assert.equal(state.transcript[1].type, 'assistant');
  assert.equal(state.transcript[1].parts[0].text, 'Hi, I can help.');
  assert.equal(state.transcript[2].parts[0].type, 'tool');
  assert.equal(state.transcript[2].parts[0].tool_id, 'call-1');
  assert.equal(state.transcript[2].parts[0].content_text, '{"path":"a"}\nfile body');
  assert.equal(state.transcript[3].parts[0].text, 'All done.');
  assert.equal(state.subagent_transcripts.child[0].text, 'work');
  assert.equal(state.subagent_transcripts.child[1].parts[0].text, 'child reply');
});
