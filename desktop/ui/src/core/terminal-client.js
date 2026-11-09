/** WebSocket transport for the shell pane. */

import { validate_output_frame } from './cli-stream.js';

const INPUT_BATCH_MS = 12;
const RESIZE_DEBOUNCE_MS = 120;

export function decode_terminal_frame(buffer) {
  if (!(buffer instanceof ArrayBuffer) || buffer.byteLength < 8) return null;
  const view = new DataView(buffer);
  const seq = Number(view.getBigUint64(0, false));
  return { seq, data: new Uint8Array(buffer, 8) };
}

export class TerminalClient {
  constructor(socket, handlers = {}) {
    this.socket = socket;
    this.handlers = handlers;
    this.seq = 0;
    this.closed = false;
    this._input = [];
    this._flush_timer = null;
    this._resize_timer = null;
    this._resize = null;

    socket.binaryType = 'arraybuffer';
    socket.onmessage = (event) => this._on_message(event);
    socket.onclose = () => this._on_close();
    socket.onerror = () => this._on_close();
  }

  send_input(data) {
    if (this.closed || !data) return;
    this._input.push(data);
    if (this._flush_timer !== null) return;
    this._flush_timer = setTimeout(() => this.flush_input(), INPUT_BATCH_MS);
  }

  flush_input() {
    this._flush_timer = null;
    if (this.closed || !this._input.length) return;
    const data = this._input.join('');
    this._input = [];
    try {
      this.socket.send(JSON.stringify({ type: 'input', data }));
    } catch (error) {
      this._on_close();
    }
  }

  resize(cols, rows) {
    this._resize = { cols, rows };
    if (this._resize_timer !== null) return;
    this._resize_timer = setTimeout(() => {
      this._resize_timer = null;
      const size = this._resize;
      this._resize = null;
      if (this.closed || !size) return;
      try {
        this.socket.send(JSON.stringify({ type: 'resize', ...size }));
      } catch (error) {
        this._on_close();
      }
    }, RESIZE_DEBOUNCE_MS);
  }

  close() {
    if (this.closed) return;
    this._on_close();
    try {
      this.socket.close();
    } catch (error) {
      /* already closed */
    }
  }

  _on_message(event) {
    if (this.closed) return;
    if (typeof event.data === 'string') {
      this._on_text(event.data);
      return;
    }
    if (event.data instanceof ArrayBuffer) {
      const frame = decode_terminal_frame(event.data);
      if (!frame) return;

      const end = frame.seq;
      const start = end - frame.data.byteLength;

      if (start < this.seq) {
        const overlap = this.seq - start;
        if (overlap >= frame.data.byteLength) return;
        this.seq = end;
        this.handlers.on_data?.(frame.data.subarray(overlap));
        return;
      }

      if (start > this.seq) {
        this.handlers.on_gap?.({ since: this.seq });
        return;
      }

      this.seq = end;
      this.handlers.on_data?.(frame.data);
    }
  }

  _on_text(text) {
    let message = null;
    try {
      message = JSON.parse(text);
    } catch (error) {
      return;
    }
    if (!message || typeof message !== 'object') return;
    if (message.type === 'ready') {
      this.seq = Number(message.seq) || 0;
      this.handlers.on_ready?.(message);
    } else if (message.type === 'reset') {
      this.seq = Number(message.seq) || 0;
      this.handlers.on_reset?.(message);
    } else if (message.type === 'exit') {
      this.handlers.on_exit?.(message);
    } else if (message.type === 'error') {
      this.handlers.on_error?.(message.message || 'terminal error');
    }
  }

  _on_close() {
    if (this.closed) return;
    this.closed = true;
    if (this._flush_timer !== null) clearTimeout(this._flush_timer);
    if (this._resize_timer !== null) clearTimeout(this._resize_timer);
    this._flush_timer = null;
    this._resize_timer = null;
    this.handlers.on_close?.();
  }
}
