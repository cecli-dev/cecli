import assert from 'node:assert/strict';
import test from 'node:test';

import { TerminalWriteQueue } from '../src/core/terminal-write-queue.js';

test('the queue merges chunks into one ordered write', () => {
  const writes = [];
  let scheduled = null;
  const queue = new TerminalWriteQueue((data) => writes.push(data), (fn) => { scheduled = fn; });

  queue.enqueue(new TextEncoder().encode('ab'));
  queue.enqueue(new TextEncoder().encode('cd'));
  assert.equal(writes.length, 0);

  scheduled();
  assert.equal(writes.length, 1);
  assert.equal(new TextDecoder().decode(writes[0]), 'abcd');
});

test('reset drops pending pre-reset bytes', () => {
  const writes = [];
  let scheduled = null;
  const queue = new TerminalWriteQueue((data) => writes.push(data), (fn) => { scheduled = fn; });

  queue.enqueue(new TextEncoder().encode('old'));
  queue.reset();
  scheduled();
  queue.enqueue(new TextEncoder().encode('new'));
  queue.flush();

  assert.equal(writes.length, 1);
  assert.equal(new TextDecoder().decode(writes[0]), 'new');
});

test('dispose blocks later writes', () => {
  const writes = [];
  const queue = new TerminalWriteQueue((data) => writes.push(data), () => {});
  queue.dispose();
  queue.enqueue(new TextEncoder().encode('x'));
  queue.flush();
  assert.equal(writes.length, 0);
});