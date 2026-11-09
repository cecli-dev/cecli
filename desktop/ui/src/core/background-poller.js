/** Visibility-aware fallback poll for CLI background state. Events are primary. */

export const POLL_VISIBLE_MS = 2000;
export const POLL_COLLAPSED_MS = 5000;

export class BackgroundPoller {
  constructor({ fetch_state, on_state, on_error, is_visible = () => true, is_collapsed = () => false }) {
    this.fetch_state = fetch_state;
    this.on_state = on_state;
    this.on_error = on_error;
    this.is_visible = is_visible;
    this.is_collapsed = is_collapsed;
    this.bridge_id = null;
    this.supported = true;
    this._timer = null;
    this._inflight = false;
    this._generation = 0;
  }

  set_bridge(bridge_id) {
    if (this.bridge_id === bridge_id) return;

    this.bridge_id = bridge_id || null;
    this.supported = true;
    this._generation += 1;
    this.stop();

    if (this.bridge_id) this.schedule();
  }

  start() {
    this.schedule();
  }

  stop() {
    if (this._timer !== null) clearTimeout(this._timer);
    this._timer = null;
  }

  schedule() {
    this.stop();
    if (!this.bridge_id || !this.supported) return;
    if (typeof document !== 'undefined' && document.hidden) return;

    const delay = this.is_collapsed() ? POLL_COLLAPSED_MS : POLL_VISIBLE_MS;
    this._timer = setTimeout(() => this.tick(), delay);
  }

  async tick() {
    if (!this.bridge_id || this._inflight || !this.supported) return;
    if (!this.is_visible()) {
      this.schedule();
      return;
    }

    const bridge_id = this.bridge_id;
    const generation = this._generation;
    this._inflight = true;

    try {
      const result = await this.fetch_state(bridge_id);
      if (bridge_id !== this.bridge_id || generation !== this._generation) return;
      this.on_state?.(result, { bridge_id, baseline: false });
    } catch (error) {
      if (bridge_id !== this.bridge_id || generation !== this._generation) return;
      if (error?.status === 404 || error?.status === 501) this.supported = false;
      this.on_error?.(error);
    } finally {
      this._inflight = false;
      if (bridge_id === this.bridge_id && generation === this._generation) this.schedule();
    }
  }
}