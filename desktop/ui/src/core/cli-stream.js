/** Pure replay/sequence state machine for /api/cli/stream and terminal WS frames. */

export function decode_base64(value) {
  if (typeof value !== 'string' || !value) return new Uint8Array(0);

  let binary = '';

  try {
    binary = typeof atob === 'function'
      ? atob(value)
      : Buffer.from(value, 'base64').toString('binary');
  } catch (error) {
    return null;
  }

  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return bytes;
}

export function validate_output_frame(frame, next_seq) {
  if (!frame || !(frame.data instanceof Uint8Array)) return { kind: 'ignore', next_seq };

  const end = Number(frame.seq);
  if (!Number.isFinite(end)) return { kind: 'ignore', next_seq };

  const start = end - frame.data.byteLength;

  if (start < next_seq) {
    const overlap = next_seq - start;
    if (overlap >= frame.data.byteLength) return { kind: 'duplicate', next_seq };

    return {
      kind: 'append',
      data: frame.data.subarray(overlap),
      next_seq: end,
    };
  }

  if (start > next_seq) return { kind: 'gap', next_seq };
  return { kind: 'append', data: frame.data, next_seq: end };
}

export class CliStreamState {
  constructor({ since = 0, decode = decode_base64 } = {}) {
    this.next_seq = Math.max(0, Number(since) || 0);
    this.decode = decode;
    this.exited = false;
    this.exit_code = null;
  }

  apply(message) {
    if (!message || typeof message !== 'object') return null;

    if (message.type === 'ready') {
      const seq = Number(message.seq);
      this.next_seq = Number.isFinite(seq) ? Math.max(0, seq) : this.next_seq;
      return { kind: 'ready', next_seq: this.next_seq, message };
    }

    if (message.type === 'reset') {
      const seq = Number(message.seq);
      if (Number.isFinite(seq)) this.next_seq = Math.max(0, seq);
      return { kind: 'reset', next_seq: this.next_seq, message };
    }

    if (message.type === 'output') {
      const data = this.decode(message.data);
      if (!data) return null;

      const result = validate_output_frame({ seq: message.seq, data }, this.next_seq);
      this.next_seq = result.next_seq;

      if (result.kind === 'gap') {
        return { kind: 'gap', next_seq: this.next_seq, message };
      }
      if (result.kind === 'duplicate') return null;
      if (result.kind === 'append') {
        return { kind: 'append', data: result.data, next_seq: this.next_seq, message };
      }
      return null;
    }

    if (message.type === 'exit') {
      this.exited = true;
      this.exit_code = message.code ?? null;
      return { kind: 'exit', code: message.code ?? null, signal: message.signal ?? null, message };
    }

    if (message.type === 'needs_input') {
      return {
        kind: 'state',
        state: 'needs_input',
        needs_input: true,
        last_prompt: message.lastPrompt || '',
        message,
      };
    }
    if (message.type === 'state') {
      return {
        kind: 'state',
        state: message.state || '',
        needs_input: Boolean(message.needsInput),
        last_prompt: message.lastPrompt || '',
        exit_code: message.exitCode ?? null,
        ended_at: message.endedAt ?? null,
        message,
      };
    }
    if (message.type === 'event') {
      return { kind: 'event', event: message.event || '', message };
    }
    if (message.type === 'error') {
      return { kind: 'error', error: message.message || 'stream error', message };
    }

    return null;
  }
}