import assert from 'node:assert/strict';
import test from 'node:test';

import {
  AUTO_CLOSE_MS,
  MAX_BACKGROUND_TABS,
  apply_cli_event,
  auto_close_due,
  bg_key,
  classify_input_error,
  close_tab,
  count_unread,
  create_default_tabs,
  input_payload,
  logs_key,
  reconcile_tabs,
  shell_key,
  shell_tab_key,
  shell_tab_label,
  workspace_key,
} from '../src/core/cli-tabs.js';

const now = 1_000_000;

function command(key, patch = {}) {
  return {
    key,
    cli_id: `bg:b1:${key}`,
    command: `python ${key}.py`,
    running: true,
    state: 'running',
    total_chars: 10,
    ...patch,
  };
}

function live_tabs(commands = [], options = {}) {
  return reconcile_tabs(create_default_tabs('ws', true), commands, {
    workspace_key: 'ws',
    bridge_id: 'b1',
    now,
    ...options,
  });
}

test('workspace key and stable tab keys', () => {
  assert.equal(workspace_key({ workspace: '/repo/name/' }), '/repo/name');
  assert.equal(workspace_key({ bridge_id: 'b1' }), 'b1');
  assert.equal(workspace_key({}), 'unassigned');
  assert.equal(logs_key('ws'), 'logs:ws');
  assert.equal(shell_key('ws'), 'shell:ws');
  assert.equal(bg_key('b1', 'bg_1'), 'bg:b1:bg_1');
  assert.notEqual(bg_key('b1', 'bg_1'), bg_key('b2', 'bg_1'));
});

test('shell tab keys and labels derive from terminal ids', () => {
  assert.equal(shell_tab_key('ws'), 'shell:ws');
  assert.equal(shell_tab_key('ws', 'term:b1:2'), 'shell:ws:term:b1:2');
  assert.equal(shell_tab_label({ id: 'term:b1:2' }), 'Shell 2');
  assert.equal(shell_tab_label({ id: 'custom' }), 'Shell');
  assert.equal(shell_tab_label(null), 'Shell');
});

test('default tabs include Shell only when terminal is enabled', () => {
  const enabled = create_default_tabs('ws', true).map((tab) => tab.kind);
  const disabled = create_default_tabs('ws', false).map((tab) => tab.kind);
  assert.deepEqual(enabled, ['logs', 'shell']);
  assert.deepEqual(disabled, ['logs']);
});

test('reconcile creates running foreground and ignores persist-only commands', () => {
  const { tabs } = live_tabs([
    command('bg_1'),
    command('bg_2', { persist: true, continued_in_background: false }),
  ]);
  const bg = tabs.filter((tab) => tab.kind === 'bg');
  assert.equal(bg.length, 1);
  assert.equal(bg[0].key, 'bg:b1:bg_1');
  assert.equal(bg[0].status, 'running');
});

test('first poll baselines finished commands; later polls create exited tabs', () => {
  const finished = command('bg_1', { running: false, state: 'exited', exit_code: 0 });
  const baseline = live_tabs([finished], { baseline: true });
  assert.equal(baseline.tabs.filter((tab) => tab.kind === 'bg').length, 0);

  const later = live_tabs([finished]);
  const bg = later.tabs.filter((tab) => tab.kind === 'bg');
  assert.equal(bg.length, 1);
  assert.equal(bg[0].status, 'exited');
});

test('continued_in_background creates the tab before the next poll', () => {
  const { tabs } = live_tabs([command('bg_1', { persist: true, continued_in_background: true })]);
  assert.equal(tabs.filter((tab) => tab.kind === 'bg').length, 1);
});

test('unread grows only while a tab is inactive', () => {
  const first = live_tabs([command('bg_1')]);
  const key = first.tabs.find((tab) => tab.kind === 'bg').key;
  const active = live_tabs([command('bg_1', { total_chars: 99 })], {
    active_key: key, tabs: first.tabs,
  });
  assert.equal(active.tabs.find((tab) => tab.key === key).unread, 0);

  const first_round = live_tabs([command('bg_1')]);
  const inactive = reconcile_tabs(first_round.tabs, [command('bg_1', { total_chars: 30 })], {
    workspace_key: 'ws', bridge_id: 'b1', now,
  });
  assert.equal(inactive.tabs.find((tab) => tab.key === key).unread, 1);
  assert.equal(count_unread(inactive.tabs), 1);
});

test('missing live command becomes lost but finished tabs are retained', () => {
  const first = live_tabs([command('bg_1'), command('bg_2', { running: false, state: 'exited' })]);
  const next = reconcile_tabs(first.tabs, [], { workspace_key: 'ws', bridge_id: 'b1', now });
  const [one, two] = next.tabs.filter((tab) => tab.kind === 'bg');
  assert.equal(one.status, 'lost');
  assert.equal(two.status, 'exited');
});

test('pressure keeps at most eight background tabs and archives finished first', () => {
  const commands = [];
  for (let index = 0; index < 10; index += 1) {
    commands.push(command(`bg_${index}`, {
      running: index >= 8,
      state: index >= 8 ? 'running' : 'exited',
      ended_at: index,
    }));
  }

  const { tabs, archived } = live_tabs(commands);
  const bg = tabs.filter((tab) => tab.kind === 'bg');
  assert.equal(bg.length, MAX_BACKGROUND_TABS);
  assert.equal(archived.length, 2);
  assert.ok(bg.some((tab) => tab.status === 'running'));
});

test('tab close selects the previous tab, else Logs', () => {
  const { tabs } = live_tabs([command('bg_1'), command('bg_2')]);
  const bg = tabs.filter((tab) => tab.kind === 'bg');
  const closed = close_tab(tabs, bg[1].key, bg[1].key);
  assert.equal(closed.active_key, bg[0].key);

  const only = close_tab(create_default_tabs('ws', true), 'shell:ws', 'shell:ws');
  assert.equal(only.active_key, 'logs:ws');
});

test('auto-close requires opt-in and never removes running or active tabs', () => {
  const tabs = [
    ...create_default_tabs('ws', false),
    { key: 'bg:1', kind: 'bg', status: 'exited', finished_at: now - AUTO_CLOSE_MS - 1, pinned: false },
    { key: 'bg:2', kind: 'bg', status: 'exited', finished_at: now - AUTO_CLOSE_MS - 1, pinned: false },
    { key: 'bg:3', kind: 'bg', status: 'running', finished_at: now - AUTO_CLOSE_MS - 1, pinned: false },
  ];

  assert.deepEqual(auto_close_due(tabs, { enabled: false, now }), []);
  assert.deepEqual(auto_close_due(tabs, { enabled: true, now, active_key: 'bg:1' }), ['bg:2']);
});

test('CLI events update tabs and closed removes one', () => {
  let tabs = create_default_tabs('ws', true);
  tabs = apply_cli_event(tabs, { event: 'started', key: 'bg_1', state: 'running', command: 'make' }, {
    workspace_key: 'ws', bridge_id: 'b1', now,
  });
  assert.equal(tabs.filter((tab) => tab.kind === 'bg').length, 1);

  tabs = apply_cli_event(tabs, { event: 'needs_input', key: 'bg_1' }, {
    workspace_key: 'ws', bridge_id: 'b1', now,
  });
  assert.equal(tabs.find((tab) => tab.kind === 'bg').status, 'needs_input');

  tabs = apply_cli_event(tabs, { event: 'exited', key: 'bg_1', code: 3 }, {
    workspace_key: 'ws', bridge_id: 'b1', now,
  });
  assert.equal(tabs.find((tab) => tab.kind === 'bg').exit_code, 3);

  tabs = apply_cli_event(tabs, { event: 'closed', key: 'bg_1' }, {
    workspace_key: 'ws', bridge_id: 'b1', now,
  });
  assert.equal(tabs.filter((tab) => tab.kind === 'bg').length, 0);
});

test('input payloads add newlines only when requested', () => {
  assert.deepEqual(input_payload({ bridge_id: 'b1', cli_id: 'bg:b1:1', input_seq: 1, text: 'yes' }), {
    bridgeId: 'b1', cliId: 'bg:b1:1', inputSeq: 1, owner: 'ui', data: 'yes\n',
  });
  assert.equal(input_payload({ bridge_id: 'b1', cli_id: 'bg:b1:1', input_seq: 2, text: 'yes', newline: false }).data, 'yes');
});

test('input errors follow 409 > 423 > 429 > 413 > 404 mapping', () => {
  assert.equal(classify_input_error(409, { error: 'input_locked' }).action, 'exited');
  assert.equal(classify_input_error(423, { error: 'input_locked' }).action, 'locked');
  assert.equal(classify_input_error(429, { error: 'queue_full' }).action, 'busy');
  assert.equal(classify_input_error(413, { error: 'too_large' }).action, 'too_large');
  assert.equal(classify_input_error(404, { error: 'not_found' }).action, 'lost');
  assert.equal(classify_input_error(501, {}).action, 'unsupported');
});