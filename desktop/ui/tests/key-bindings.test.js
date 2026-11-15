import assert from 'node:assert/strict';
import test from 'node:test';

import {
  binding_label,
  event_key,
  matches_key_binding,
  normalize_key_bindings,
} from '../src/core/key-bindings.js';

function key_event(key, modifiers = {}) {
  return {
    key,
    code: modifiers.code || '',
    altKey: Boolean(modifiers.alt),
    ctrlKey: Boolean(modifiers.ctrl),
    shiftKey: Boolean(modifiers.shift),
    metaKey: Boolean(modifiers.meta),
    isComposing: false,
  };
}

test('paste binding defaults to alt+v', () => {
  const bindings = normalize_key_bindings({});

  assert.equal(matches_key_binding(bindings, 'paste', key_event('v', { alt: true })), true);
  assert.equal(matches_key_binding(bindings, 'paste', key_event('v')), false);
});
test('default submit and newline bindings match plain and shifted enter', () => {
  const bindings = normalize_key_bindings({});

  assert.equal(matches_key_binding(bindings, 'submit', key_event('Enter')), true);
  assert.equal(matches_key_binding(bindings, 'newline', key_event('Enter', { shift: true })), true);
  assert.equal(matches_key_binding(bindings, 'submit', key_event('Enter', { shift: true })), false);
  assert.equal(matches_key_binding(bindings, 'newline', key_event('j', { ctrl: true })), true);
});

test('custom bindings replace the defaults for that action only', () => {
  const bindings = normalize_key_bindings({ submit: 'ctrl+j', newline: 'enter' });

  assert.equal(matches_key_binding(bindings, 'submit', key_event('j', { ctrl: true })), true);
  assert.equal(matches_key_binding(bindings, 'submit', key_event('Enter', { shift: true })), true);
  assert.equal(matches_key_binding(bindings, 'submit', key_event('Enter')), false);
  assert.equal(matches_key_binding(bindings, 'newline', key_event('Enter')), true);
  assert.equal(matches_key_binding(bindings, 'panel_cycle', key_event('o', { alt: true })), true);
});

test('option-letter falls back to the physical key on macOS', () => {
  const bindings = normalize_key_bindings({});
  const event = key_event('π', { alt: true, code: 'KeyP' });

  assert.equal(event_key(event), 'alt+p');
  assert.equal(matches_key_binding(bindings, 'panels', event), true);
  assert.equal(matches_key_binding(bindings, 'panel_cycle', event), false);
});

test('modifier order does not matter and comma lists match any key', () => {
  const bindings = normalize_key_bindings({ next_agent: 'ctrl+alt+right, ctrl+j' });

  assert.equal(event_key(key_event('ArrowRight', { alt: true, ctrl: true })), 'alt+ctrl+right');
  assert.equal(
    matches_key_binding(bindings, 'next_agent', key_event('ArrowRight', { alt: true, ctrl: true })),
    true,
  );
  assert.equal(matches_key_binding(bindings, 'next_agent', key_event('j', { ctrl: true })), true);
});

test('labels match the TUI key names', () => {
  const bindings = normalize_key_bindings({ next_agent: 'ctrl+alt+right' });

  assert.equal(binding_label(bindings, 'submit'), 'Enter');
  assert.equal(binding_label(bindings, 'newline'), 'Shift+Enter');
  assert.equal(binding_label(bindings, 'next_agent'), 'Ctrl+Alt+Right');
  assert.equal(binding_label({ submit: 'ctrl+j' }, 'submit'), 'Shift+Enter');
  assert.equal(binding_label(bindings, 'stop'), 'Escape');
});
