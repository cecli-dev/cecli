import assert from 'node:assert/strict';
import test from 'node:test';

import {
  clear_terminal_logs,
  get_terminal_logs,
  push_terminal_log,
  subscribe_terminal_log,
} from '../src/core/log-bus.js';
import { decode_terminal_frame, TerminalClient } from '../src/core/terminal-client.js';

test('terminal log bus caps and notifies subscribers', () => {
  clear_terminal_logs();
  for (let index = 0; index < 2005; index += 1) {
    push_terminal_log({ level: 'info', message: `line ${index}` });
  }
  const logs = get_terminal_logs();
  assert.equal(logs.length, 2000);
  assert.equal(logs[logs.length - 1].message, 'line 2004');

  let seen = 0;
  const unsubscribe = subscribe_terminal_log(() => {
    seen += 1;
  });
  push_terminal_log({ level: 'warning', message: 'one more' });
  unsubscribe();
  push_terminal_log({ level: 'warning', message: 'ignored' });
  assert.equal(seen, 1);
});

test('terminal frames carry a big-endian sequence prefix', () => {
  const payload = new TextEncoder().encode('hello');
  const buffer = new ArrayBuffer(8 + payload.length);
  new DataView(buffer).setBigUint64(0, 42n, false);
  new Uint8Array(buffer, 8).set(payload);

  const frame = decode_terminal_frame(buffer);
  assert.equal(frame.seq, 42);
  assert.equal(new TextDecoder().decode(frame.data), 'hello');
  assert.equal(decode_terminal_frame(new ArrayBuffer(2)), null);
});

test('terminal client batches input frames', () => {
  const sent = [];
  const socket = {
    send: (data) => sent.push(JSON.parse(data)),
    close: () => {},
  };
  const client = new TerminalClient(socket, {});
  client.send_input('ab');
  client.send_input('c');
  client.flush_input();

  assert.deepEqual(sent, [{ type: 'input', data: 'abc' }]);
  client.close();
});

test('a ready offset earlier than the frame end replays the buffered bytes', () => {
  const replay = replay_client();
  replay.ready(1);
  replay.send_frame(3, 'bc');

  assert.deepEqual(replay.data, ['bc']);
  assert.equal(replay.client.seq, 3);
});

test('an END-valued ready offset drops replay (guards the server seq contract)', () => {
  const replay = replay_client();
  replay.ready(3);
  replay.send_frame(3, 'bc');

  assert.deepEqual(replay.data, []);
  assert.equal(replay.client.seq, 3);
});

test('a live frame after a caught-up ready appends instead of reporting a gap', () => {
  const replay = replay_client();
  replay.ready(3);
  replay.send_frame(6, 'def');

  assert.deepEqual(replay.data, ['def']);
  assert.deepEqual(replay.gaps, []);
});

function terminal_frame(seq, text) {
  const payload = new TextEncoder().encode(text);
  const buffer = new ArrayBuffer(8 + payload.length);
  new DataView(buffer).setBigUint64(0, BigInt(seq), false);
  new Uint8Array(buffer, 8).set(payload);
  return buffer;
}

function replay_client() {
  const socket = { binaryType: '', send: () => {}, close: () => {} };
  const data = [];
  const gaps = [];
  const client = new TerminalClient(socket, {
    on_data: (bytes) => data.push(new TextDecoder().decode(bytes)),
    on_gap: (info) => gaps.push(info),
  });
  const ready = (seq) => socket.onmessage({ data: JSON.stringify({ type: 'ready', seq }) });
  const send_frame = (seq, text) => socket.onmessage({ data: terminal_frame(seq, text) });

  return { client, data, gaps, ready, send_frame };
}
