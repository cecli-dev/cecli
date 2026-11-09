import { get_desktop_token } from './token.js';
/** Command-only WebSocket channel; SSE remains the server-to-client delta stream. */
export class BridgeSocket {
  constructor() {
    this.socket = null;
    this.pending = new Map();
    this.sequence = 0;
    this.open_promise = null;
  }

  get ready() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  async connect() {
    if (this.ready) return true;
    if (this.open_promise) return this.open_promise;

    this.open_promise = new Promise((resolve) => {
      const token = get_desktop_token();
      const protocols = ['cecli.desktop.v1'];
      if (token) protocols.push(`token.${token}`);
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
      let socket;
      try {
        socket = new WebSocket(`${scheme}://${window.location.host}/ws`, protocols);
      } catch (error) {
        this.open_promise = null;
        resolve(false);
        return;
      }

      this.socket = socket;
      socket.onopen = () => {
        this.open_promise = null;
        resolve(true);
      };
      socket.onmessage = (event) => this._receive(event.data);
      socket.onclose = () => {
        this.socket = null;
        this.open_promise = null;
        this._reject_pending('WebSocket closed');
      };
      socket.onerror = () => {
        this.open_promise = null;
        this._reject_pending('WebSocket error');
        resolve(false);
      };
    });

    return this.open_promise;
  }

  async request(command, params = {}) {
    if (!this.ready && !(await this.connect())) {
      throw new Error('WebSocket is unavailable');
    }

    this.sequence += 1;
    const id = `c${this.sequence}`;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try {
        this.socket.send(JSON.stringify({ id, command, params }));
      } catch (error) {
        this.pending.delete(id);
        reject(error);
      }
    });
  }

  _receive(raw) {
    let message;
    try {
      message = JSON.parse(raw);
    } catch (error) {
      return;
    }

    if (!message || message.id === undefined) return;
    const entry = this.pending.get(message.id);
    if (!entry) return;
    this.pending.delete(message.id);

    if (message.ok) entry.resolve(message.result);
    else entry.reject(new Error(message.error || 'WebSocket command failed'));
  }

  _reject_pending(message) {
    for (const entry of this.pending.values()) entry.reject(new Error(message));
    this.pending.clear();
  }
}

export const bridge_socket = new BridgeSocket();