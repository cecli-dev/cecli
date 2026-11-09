import assert from 'node:assert/strict';
import test from 'node:test';

import { CliStreamState, decode_base64, validate_output_frame } from '../src/core/cli-stream.js';

function encode(bytes) {
  return Buffer.from(bytes).toString('base64');
}

test('first connect with buffered bytes appends without reset', () => {
  const stream = new CliStreamState({ since: 0 });
  assert.equal(stream.apply({ type: 'ready', seq: 0 }).kind, 'ready');

  const action = stream.apply({ type: 'output', seq: 5, data: encode('hello') });
  assert.equal(action.kind, 'append');
  assert.equal(new TextDecoder().decode(action.data), 'hello');
  assert.equal(stream.next_seq, 5);
});

test('reconnect with since>0 uses the first-byte ready offset', () => {
  const stream = new CliStreamState({ since: 5 });
  const ready = stream.apply({ type: 'ready', seq: 5, startSeq: 0 });
  assert.equal(ready.kind, 'ready');
  assert.equal(ready.next_seq, 5);

  const action = stream.apply({ type: 'output', seq: 10, data: encode('world') });
  assert.equal(action.kind, 'append');
  assert.equal(new TextDecoder().decode(action.data), 'world');
});

test('duplicate/overlap frames append only the unseen suffix', () => {
  const stream = new CliStreamState({ since: 5 });
  const action = stream.apply({ type: 'output', seq: 8, data: encode('abcdefgh') });
  assert.equal(action.kind, 'append');
  assert.equal(new TextDecoder().decode(action.data), 'fgh');
  assert.equal(stream.next_seq, 8);
});

test('a gap reports needs-resync without resetting bytes', () => {
  const stream = new CliStreamState({ since: 5 });
  const action = stream.apply({ type: 'output', seq: 20, data: encode('late') });
  assert.equal(action.kind, 'gap');
  assert.equal(stream.next_seq, 5);
});

test('reset rebases to the snapshot start offset', () => {
  const stream = new CliStreamState({ since: 90 });
  const action = stream.apply({ type: 'reset', seq: 10 });
  assert.equal(action.kind, 'reset');
  assert.equal(stream.next_seq, 10);
});

test('exit records the final code', () => {
  const stream = new CliStreamState();
  const action = stream.apply({ type: 'exit', code: 7 });
  assert.equal(action.kind, 'exit');
  assert.equal(action.code, 7);
  assert.equal(stream.exited, true);
});

test('base64 round-trips and invalid input is ignored', () => {
  assert.equal(new TextDecoder().decode(decode_base64(encode('abc'))), 'abc');
  assert.equal(decode_base64('%%%'), null);
});

test('terminal frame validation accepts end offsets and rejects start offsets', () => {
  const data = new TextEncoder().encode('abcd');
  assert.equal(validate_output_frame({ seq: 4, data }, 0).kind, 'append');
  assert.equal(validate_output_frame({ seq: 4, data }, 4).kind, 'duplicate');
  assert.equal(validate_output_frame({ seq: 8, data }, 4).kind, 'append');
  assert.equal(validate_output_frame({ seq: 9, data }, 4).kind, 'gap');
  assert.equal(validate_output_frame({ seq: 2, data }, 4).kind, 'duplicate');
});

test('state frames carry prompt and exit metadata', () => {
  const stream = new CliStreamState({ since: 0 });
  const state = stream.apply({
    type: 'state',
    state: 'needs_input',
    needsInput: true,
    lastPrompt: '[sudo] password:',
  });

  assert.equal(state.kind, 'state');
  assert.equal(state.state, 'needs_input');
  assert.equal(state.needs_input, true);
  assert.equal(state.last_prompt, '[sudo] password:');

  const exit = stream.apply({ type: 'exit', code: 7, signal: null });
  assert.equal(exit.kind, 'exit');
  assert.equal(exit.code, 7);
  assert.equal(stream.exited, true);
});

test('needs_input frames map to a prompt badge state', () => {
  const stream = new CliStreamState({ since: 0 });
  const action = stream.apply({ type: 'needs_input', lastPrompt: '[sudo] password:' });

  assert.equal(action.kind, 'state');
  assert.equal(action.state, 'needs_input');
  assert.equal(action.needs_input, true);
  assert.equal(action.last_prompt, '[sudo] password:');
});