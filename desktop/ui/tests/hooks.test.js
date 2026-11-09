import assert from 'node:assert/strict';
import test from 'node:test';

import { HOOK_SECTIONS, group_hooks, hook_section_label } from '../src/core/hooks.js';

test('hook sections use the six /hooks types in run order', () => {
  assert.deepEqual(
    HOOK_SECTIONS.map((section) => section.type),
    ['start', 'on_message', 'end_message', 'pre_tool', 'post_tool', 'end'],
  );
  assert.deepEqual(
    HOOK_SECTIONS.map((section) => section.label),
    ['Start', 'On message', 'End message', 'Pre tool', 'Post tool', 'End'],
  );
});

test('group_hooks orders sections by hook type, not input order', () => {
  const sections = group_hooks([
    { name: 'notify', type: 'end', priority: 1 },
    { name: 'lint', type: 'start', priority: 1 },
    { name: 'guard', type: 'pre_tool', priority: 1 },
    { name: 'summarise', type: 'on_message', priority: 1 },
  ]);

  assert.deepEqual(
    sections.map((section) => section.type),
    ['start', 'on_message', 'pre_tool', 'end'],
  );
  assert.deepEqual(
    sections.map((section) => section.label),
    ['Start', 'On message', 'Pre tool', 'End'],
  );
});

test('group_hooks sorts each section by priority then name', () => {
  const sections = group_hooks([
    { name: 'zeta', type: 'pre_tool', priority: 10 },
    { name: 'alpha', type: 'pre_tool', priority: 10 },
    { name: 'first', type: 'pre_tool', priority: 1 },
    { name: 'second', type: 'pre_tool', priority: 5 },
  ]);

  assert.equal(sections.length, 1);
  assert.deepEqual(
    sections[0].hooks.map((hook) => hook.name),
    ['first', 'second', 'alpha', 'zeta'],
  );
});

test('group_hooks keeps enabled flags and skips empty input', () => {
  const sections = group_hooks([
    { name: 'guard', type: 'pre_tool', enabled: true, priority: 5 },
    { name: 'notify', type: 'on_message', enabled: false, priority: 20 },
  ]);

  assert.deepEqual(
    sections.map((section) => section.type),
    ['on_message', 'pre_tool'],
  );
  assert.equal(sections[0].hooks[0].enabled, false);
  assert.equal(sections[1].hooks[0].enabled, true);
  assert.deepEqual(group_hooks([]), []);
  assert.deepEqual(group_hooks(null), []);
  assert.deepEqual(group_hooks(undefined), []);
});

test('group_hooks ignores junk entries and appends unknown types', () => {
  const sections = group_hooks([
    null,
    'nope',
    { name: 'custom', type: 'audit_log', priority: 3 },
    { name: 'lint', type: 'start', priority: 1 },
  ]);

  assert.deepEqual(
    sections.map((section) => section.type),
    ['start', 'audit_log'],
  );
  assert.equal(sections[1].label, 'Audit log');
  assert.deepEqual(
    sections[1].hooks.map((hook) => hook.name),
    ['custom'],
  );
});

test('hook_section_label titleises unknown slugs', () => {
  assert.equal(hook_section_label('pre_tool'), 'Pre tool');
  assert.equal(hook_section_label('end_message'), 'End message');
  assert.equal(hook_section_label('post-tool'), 'Post tool');
  assert.equal(hook_section_label(''), 'Other');
});