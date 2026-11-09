/** Batched xterm writes so bursts from two transports stay ordered. */

const MAX_BATCH_BYTES = 64 * 1024;

export class TerminalWriteQueue {
  constructor(write, schedule = null) {
    this.write = write;
    this.schedule = schedule || ((callback) => setTimeout(callback, 0));
    this._chunks = [];
    this._bytes = 0;
    this._scheduled = false;
    this._disposed = false;
  }

  enqueue(data) {
    if (this._disposed || !data) return;

    const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
    if (!bytes.byteLength) return;

    this._chunks.push(bytes);
    this._bytes += bytes.byteLength;

    if (this._bytes >= MAX_BATCH_BYTES) {
      this.flush();
      return;
    }

    if (!this._scheduled) {
      this._scheduled = true;
      this.schedule(() => this.flush());
    }
  }

  flush() {
    this._scheduled = false;
    if (this._disposed || !this._chunks.length) return;

    const merged = new Uint8Array(this._bytes);
    let offset = 0;

    for (const chunk of this._chunks) {
      merged.set(chunk, offset);
      offset += chunk.byteLength;
    }

    this._chunks = [];
    this._bytes = 0;
    this.write(merged);
  }

  reset() {
    this._chunks = [];
    this._bytes = 0;
  }

  dispose() {
    this._disposed = true;
    this.reset();
  }
}