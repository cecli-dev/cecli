import { LitElement, html, nothing } from 'lit';

import { CHEVRON_ICON } from '../core/constants.js';

import {
  get_browser_state,
  close_browser_tab,
  new_browser_tab,
  open_browser_stream,
  open_browser_url,
  select_browser_tab,
  send_browser_action,
  send_browser_input,
  set_browser_viewport,
  start_browser,
} from '../core/browser-api.js';

const SPECIAL_KEYS = new Set([
  'Enter',
  'Backspace',
  'Delete',
  'Tab',
  'Escape',
  'ArrowLeft',
  'ArrowRight',
  'ArrowUp',
  'ArrowDown',
  'Home',
  'End',
  'PageUp',
  'PageDown',
  'Insert',
]);

const RECONNECT_BASE_MS = 700;
const RECONNECT_MAX_MS = 8000;
const INPUT_QUEUE_LIMIT = 32;
const VIEWPORT_MIN_PX = 32;
const VIEWPORT_SCALE = 4;
const MAX_VIEWPORT_WIDTH = 1920;
const MAX_VIEWPORT_HEIGHT = 1080;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;
const ZOOM_STEP = 1.2;

const GLOBE_ICON = html`
  <svg
    width="22"
    height="22"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <circle cx="12" cy="12" r="9"></circle>
    <path d="M3 12h18"></path>
    <path d="M12 3c2.7 2.4 4.2 5.4 4.2 9s-1.5 6.6-4.2 9c-2.7-2.4-4.2-5.4-4.2-9S9.3 5.4 12 3z"></path>
  </svg>
`;

export class BrowserPanel extends LitElement {
  constructor() {
    super();
    this._available = null;
    this._running = false;
    this._browser = '';
    this._executable = '';
    this._profile = '';
    this._port = null;
    this._url = '';
    this._title = '';
    this._error = '';
    this._viewport = { width: 0, height: 0, dpr: 1 };

    this._starting = false;
    this._navigating = false;
    this._stream_status = 'idle';
    this._url_draft = '';
    this._tabs = [];
    this._active_tab_id = null;
    this._zoom = 1;
    this._zoom_pending = false;
    this._zoom_anchor = null;
    this._switching_tab = false;
    this._creating_tab = false;
    this._collapsed = false;
    this._scroll = { x: 0, y: 0, maxX: 0, maxY: 0 };
    this._scroll_known = false;

    this._canvas = null;
    this._viewport_el = null;
    this._stage_el = null;
    this._url_input = null;
    this._last_bitmap = null;
    this._frame_meta = null;
    this._frame_rect = null;
    this._frame_ready = false;
    this._pending_frame = null;
    this._decoding = false;
    this._redraw_scheduled = false;
    this._disconnected = false;

    this._stream = null;
    this._reconnect_timer = null;
    this._reconnect_delay = RECONNECT_BASE_MS;
    this._resize_observer = null;
    this._viewport_send_timer = null;
    this._last_viewport_key = '';
    this._window_resize_bound = false;

    this._wheel_bound = false;
    this._pointer_pressed = false;
    this._pointer_button = 0;
    this._last_click_time = 0;
    this._last_click_button = -1;
    this._click_count = 0;
    this._held_keys = new Map();
    this._input_queue = [];
    this._input_flushing = false;
    this._navigating_timer = null;

    this._on_wheel = this._on_wheel.bind(this);
    this._on_viewport_resize = this._on_viewport_resize.bind(this);
    this._on_visibility_change = this._on_visibility_change.bind(this);
  }

  createRenderRoot() {
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener('visibilitychange', this._on_visibility_change);
    this._fetch_state();
    if (!document.hidden) this._connect_stream();

    if (this.hasUpdated) {
      this.updateComplete.then(() => {
        if (!this.isConnected) return;
        this._cache_elements();
        this._bind_wheel();
        this._setup_resize_observer();
        this._queue_viewport_send(0);
      });
    }
  }

  disconnectedCallback() {
    this._disconnected = true;
    document.removeEventListener('visibilitychange', this._on_visibility_change);
    this._close_stream();
    clearTimeout(this._reconnect_timer);
    this._reconnect_timer = null;
    clearTimeout(this._viewport_send_timer);
    this._viewport_send_timer = null;
    clearTimeout(this._navigating_timer);
    this._navigating_timer = null;

    if (this._resize_observer) {
      this._resize_observer.disconnect();
      this._resize_observer = null;
    }

    if (this._window_resize_bound) {
      window.removeEventListener('resize', this._on_viewport_resize);
      this._window_resize_bound = false;
    }

    if (this._canvas && this._wheel_bound) {
      this._canvas.removeEventListener('wheel', this._on_wheel);
      this._wheel_bound = false;
    }

    this._held_keys.clear();
    this._drop_frame();
    super.disconnectedCallback();
  }

  updated() {
    this.toggleAttribute('data-collapsed', this._collapsed);
    this._cache_elements();
    this._bind_wheel();
    this._setup_resize_observer();
    this._apply_zoom();

    if (this._zoom_pending) {
      const anchor = this._zoom_anchor;
      this._zoom_pending = false;
      requestAnimationFrame(() => this._after_zoom(anchor));
    }
  }

  render() {
    const running = this._running;
    const status = this._status();

    return html`
      <section class="browser-panel" aria-label="Browser">
        <header class="browser-head" @click=${this._toggle_collapsed}>
          <div class="browser-head-title">
            <span class="browser-title">Browser</span>
          </div>
          <span
            class="browser-status-text"
            data-state=${status.state}
            title=${this._status_detail()}
          >${status.label}</span>
          <button
            type="button"
            class="browser-collapse"
            title=${this._collapsed ? 'Expand browser' : 'Collapse browser'}
            aria-label=${this._collapsed ? 'Expand browser' : 'Collapse browser'}
            aria-expanded=${!this._collapsed}
            @click=${this._toggle_collapsed}
          >${CHEVRON_ICON}</button>
        </header>

        <div class="browser-toolbar" role="toolbar" aria-label="Browser controls">
          <button
            type="button"
            class="browser-icon-btn"
            title="Back"
            aria-label="Back"
            ?disabled=${!running}
            @click=${() => this._action('back')}
          >&#8592;</button>
          <button
            type="button"
            class="browser-icon-btn"
            title="Forward"
            aria-label="Forward"
            ?disabled=${!running}
            @click=${() => this._action('forward')}
          >&#8594;</button>
          <button
            type="button"
            class="browser-icon-btn"
            title=${this._navigating ? 'Stop loading' : 'Reload'}
            aria-label=${this._navigating ? 'Stop loading' : 'Reload'}
            ?disabled=${!running}
            @click=${() => this._action(this._navigating ? 'stop' : 'reload')}
          >${this._navigating ? '\u25a0' : '\u27f3'}</button>
          <input
            class="browser-url"
            type="text"
            .value=${this._url_draft}
            placeholder="Search Google or enter address"
            spellcheck="false"
            autocomplete="off"
            aria-label="Browser address"
            ?disabled=${!running}
            @input=${this._on_url_input}
            @keydown=${this._on_url_keydown}
          />
          <button
            type="button"
            class="browser-go"
            ?disabled=${!running}
            @click=${this._open_url}
          >Go</button>
        </div>

        ${this._error
          ? html`
              <div class="browser-error" role="alert">
                <span class="browser-error-text">${this._error}</span>
                <button
                  type="button"
                  class="browser-error-dismiss"
                  title="Dismiss"
                  aria-label="Dismiss error"
                  @click=${this._dismiss_error}
                >\u00d7</button>
              </div>
            `
          : nothing}
        ${this._render_tabs()}

        <div class="browser-viewport">
          <div class="browser-stage">
          <canvas
            class="browser-canvas"
            tabindex="0"
            aria-label="Browser page viewport"
            @pointerdown=${this._on_pointerdown}
            @pointermove=${this._on_pointermove}
            @pointerup=${this._on_pointerup}
            @pointercancel=${this._on_pointercancel}
            @contextmenu=${this._on_contextmenu}
            @keydown=${this._on_canvas_keydown}
            @keyup=${this._on_canvas_keyup}
            @paste=${this._on_paste}
            @blur=${this._on_canvas_blur}
          ></canvas>
          </div>
          ${this._render_overlay()}
        </div>

        <footer class="browser-foot">
          <span class="browser-foot-url" title=${this._url}>${this._title || this._url || 'No page loaded'}</span>
          <span class="browser-foot-meta">
            <span class="browser-zoom" role="group" aria-label="Canvas zoom">
              <button
                type="button"
                class="browser-zoom-btn"
                title="Zoom out canvas"
                aria-label="Zoom out canvas"
                ?disabled=${!this._running || this._zoom <= MIN_ZOOM}
                @click=${this._zoom_out}
              >\u2212</button>
              <button
                type="button"
                class="browser-zoom-value"
                title="Reset canvas zoom"
                aria-label="Reset canvas zoom"
                @click=${this._reset_zoom}
              >${Math.round(this._zoom * 100)}%</button>
              <button
                type="button"
                class="browser-zoom-btn"
                title="Zoom in canvas"
                aria-label="Zoom in canvas"
                ?disabled=${!this._running || this._zoom >= MAX_ZOOM}
                @click=${this._zoom_in}
              >+</button>
            </span>
            <span class="browser-viewport-size">${this._viewport_label()}</span>
          </span>
        </footer>
      </section>
    `;
  }

  _render_overlay() {
    if (this._running && this._frame_ready) return nothing;

    if (this._starting) {
      return this._empty_state({
        icon: html`<span class="browser-spinner"></span>`,
        title: 'Starting browser\u2026',
        description: 'Launching the local browser backend.',
      });
    }

    if (this._available === false) {
      return this._empty_state({
        icon: GLOBE_ICON,
        title: 'Browser unavailable',
        description: html`
          Chrome or Edge was not found. Install one, or set
          <code>CECLI_BROWSER_BIN</code> to the executable path and restart the bridge.
          ${this._executable
            ? html`<span class="browser-empty-hint">Last checked: <code>${this._executable}</code></span>`
            : nothing}
        `,
        actions: html`
          <button type="button" class="browser-btn" @click=${this._retry}>Retry</button>
          <button
            type="button"
            class="browser-btn browser-btn--primary"
            ?disabled=${this._starting}
            @click=${this._start}
          >Start browser</button>
        `,
      });
    }

    if (this._available === null) {
      if (this._error) {
        return this._empty_state({
          icon: GLOBE_ICON,
          title: 'Browser backend unavailable',
          description: 'The browser service did not respond. Check that the desktop bridge is running.',
          actions: html`
            <button type="button" class="browser-btn" @click=${this._retry}>Retry</button>
          `,
        });
      }

      return this._empty_state({
        icon: html`<span class="browser-spinner"></span>`,
        title: 'Checking for a browser\u2026',
        description: 'Contacting the desktop bridge.',
      });
    }

    if (!this._running) {
      return this._empty_state({
        icon: GLOBE_ICON,
        title: 'Browser is not running',
        description: 'Start a local browser to preview and interact with pages inside cecli.',
        actions: html`
          <button
            type="button"
            class="browser-btn browser-btn--primary"
            ?disabled=${this._starting}
            @click=${this._start}
          >Start browser</button>
        `,
      });
    }

    return this._empty_state({
      icon: html`<span class="browser-spinner"></span>`,
      title: 'Waiting for the first frame\u2026',
      description: this._url ? `Loading ${this._url}.` : 'The browser is running.',
    });
  }

  _empty_state({ icon, title, description, actions }) {
    return html`
      <div class="browser-empty" role="status">
        <span class="browser-empty-icon" aria-hidden="true">${icon}</span>
        <h3 class="browser-empty-title">${title}</h3>
        <p class="browser-empty-text">${description}</p>
        ${actions ? html`<div class="browser-empty-actions">${actions}</div>` : nothing}
      </div>
    `;
  }

  _status() {
    if (this._starting) return { state: 'busy', label: 'Starting\u2026' };
    if (this._stream_status === 'retrying') {
      return { state: this._running ? 'live' : 'off', label: 'Reconnecting\u2026' };
    }
    if (this._running) {
      return { state: 'live', label: this._navigating ? 'Loading\u2026' : 'Live' };
    }
    if (this._available === false) return { state: 'off', label: 'Unavailable' };
    if (this._available === null) return { state: 'busy', label: 'Checking\u2026' };
    return { state: 'ready', label: 'Ready' };
  }

  _status_detail() {
    const parts = [];

    if (this._browser) parts.push(this._browser);
    if (this._port) parts.push(`port ${this._port}`);
    if (this._profile) parts.push(this._profile);

    return parts.join(' \u00b7 ');
  }

  _viewport_label() {
    const viewport = this._viewport;

    if (!viewport || !viewport.width || !viewport.height) {
      return this._port ? `port ${this._port}` : '';
    }

    const dpr = viewport.dpr && viewport.dpr !== 1 ? ` @${viewport.dpr}x` : '';
    return `${Math.round(viewport.width)}\u00d7${Math.round(viewport.height)}${dpr}`;
  }

  _render_tabs() {
    if (!this._running) return nothing;

    return html`
      <div class="browser-tabs" role="tablist" aria-label="Browser tabs">
        ${this._tabs.map(
          (tab) => html`
            <div
              class="browser-tab"
              role="tab"
              data-active=${tab.id === this._active_tab_id}
              aria-selected=${tab.id === this._active_tab_id}
              title=${tab.title || tab.url || tab.id}
            >
              <button
                type="button"
                class="browser-tab-label"
                ?disabled=${this._switching_tab}
                @click=${() => this._select_tab(tab.id)}
              >${tab_label(tab)}</button>
              <button
                type="button"
                class="browser-tab-close"
                title="Close tab"
                aria-label="Close tab"
                ?disabled=${this._switching_tab}
                @click=${(event) => this._close_tab(tab.id, event)}
              >\u00d7</button>
            </div>
          `,
        )}
        <button
          type="button"
          class="browser-tab-new"
          title="New tab"
          aria-label="New tab"
          ?disabled=${this._creating_tab}
          @click=${this._new_tab}
        >+</button>
      </div>
    `;
  }

  _toggle_collapsed(event) {
    if (event) event.stopPropagation();
    this._collapsed = !this._collapsed;
    this.requestUpdate();
  }

  async _new_tab() {
    if (this._creating_tab) return;

    this._creating_tab = true;
    this._error = '';
    this.requestUpdate();

    try {
      const data = await new_browser_tab();
      if (data && typeof data === 'object') this._apply_state(data);
    } catch (error) {
      this._set_error(error);
    } finally {
      this._creating_tab = false;
      this.requestUpdate();
    }
  }

  async _close_tab(tab_id, event) {
    event?.stopPropagation();
    if (!tab_id || this._switching_tab) return;

    this._switching_tab = true;
    this._error = '';
    this.requestUpdate();

    try {
      const data = await close_browser_tab(tab_id);
      if (data && typeof data === 'object') this._apply_state(data);
    } catch (error) {
      this._set_error(error);
    } finally {
      this._switching_tab = false;
      this.requestUpdate();
    }
  }

  async _select_tab(tab_id) {
    if (!tab_id || this._switching_tab || tab_id === this._active_tab_id) return;

    this._switching_tab = true;
    this._error = '';
    this.requestUpdate();

    try {
      const data = await select_browser_tab(tab_id);
      if (data && typeof data === 'object') this._apply_state(data);
    } catch (error) {
      this._set_error(error);
    } finally {
      this._switching_tab = false;
      this.requestUpdate();
    }
  }

  _zoom_in() {
    this._set_zoom(this._zoom * ZOOM_STEP);
  }

  _zoom_out() {
    this._set_zoom(this._zoom / ZOOM_STEP);
  }

  _reset_zoom() {
    this._set_zoom(1);
  }

  _set_zoom(value, anchor = null) {
    const next = Number(clamp(value, MIN_ZOOM, MAX_ZOOM).toFixed(2));
    if (next === this._zoom) return;

    this._zoom_anchor = anchor || this._center_anchor();
    this._zoom = next;
    this._zoom_pending = true;
    this.requestUpdate();
  }

  _center_anchor() {
    const stage = this._stage_el;
    const viewport = this._viewport_el;
    if (!stage || !viewport || !stage.offsetWidth || !stage.offsetHeight) return null;

    return {
      x: clamp(
        (viewport.scrollLeft + viewport.clientWidth / 2 - stage.offsetLeft) / stage.offsetWidth,
        0,
        1,
      ),
      y: clamp(
        (viewport.scrollTop + viewport.clientHeight / 2 - stage.offsetTop) / stage.offsetHeight,
        0,
        1,
      ),
    };
  }

  _pointer_anchor(event) {
    const stage = this._stage_el;
    if (!stage) return null;

    const rect = stage.getBoundingClientRect();
    return {
      x: clamp((event.clientX - rect.left) / Math.max(rect.width, 1), 0, 1),
      y: clamp((event.clientY - rect.top) / Math.max(rect.height, 1), 0, 1),
    };
  }

  _apply_zoom() {
    const stage = this._stage_el;
    if (!stage) return;

    const width = `${(this._zoom * 100).toFixed(2)}%`;
    const height = `${(this._zoom * 100).toFixed(2)}%`;
    if (stage.style.width !== width) stage.style.width = width;
    if (stage.style.height !== height) stage.style.height = height;
  }

  _after_zoom(anchor) {
    if (this._disconnected) return;

    const stage = this._stage_el;
    const viewport = this._viewport_el;
    if (stage && viewport && anchor) {
      viewport.scrollLeft = Math.max(
        0,
        stage.offsetLeft + anchor.x * stage.offsetWidth - viewport.clientWidth / 2,
      );
      viewport.scrollTop = Math.max(
        0,
        stage.offsetTop + anchor.y * stage.offsetHeight - viewport.clientHeight / 2,
      );
    }

    if (this._last_bitmap) this._draw_bitmap(this._last_bitmap);
  }

  _on_url_input(event) {
    this._url_draft = event.target.value;
  }

  _on_url_keydown(event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      this._open_url();
    } else if (event.key === 'Escape') {
      event.stopPropagation();
    }
  }

  async _open_url() {
    const url = navigation_url(this._url_draft);
    if (!url) {
      if (this._url_input) this._url_input.focus();
      return;
    }

    this._url_draft = url;
    this._set_navigating(true);
    this._error = '';
    this.requestUpdate();

    try {
      const data = await open_browser_url(url);
      if (data && typeof data === 'object') this._apply_state(data);
    } catch (error) {
      this._set_navigating(false);
      this._set_error(error);
    }
  }

  async _action(action) {
    if (!this._running) return;
    if (action !== 'stop') this._set_navigating(true);
    else this._set_navigating(false);

    try {
      const data = await send_browser_action(action);
      if (data && typeof data === 'object') this._apply_state(data);
    } catch (error) {
      this._set_navigating(false);
      this._set_error(error);
    }
  }

  async _start() {
    if (this._starting) return;
    this._starting = true;
    this._error = '';
    this.requestUpdate();

    try {
      const data = await start_browser();
      if (data && typeof data === 'object') this._apply_state(data);
      if (!data || !('running' in data)) this._running = true;
      this._last_viewport_key = '';
      this._queue_viewport_send(0);
    } catch (error) {
      this._set_error(error);
    } finally {
      this._starting = false;
      this.requestUpdate();
    }
  }

  _retry() {
    this._available = null;
    this._error = '';
    this.requestUpdate();
    this._connect_stream();
    this._fetch_state();
  }

  _dismiss_error() {
    this._error = '';
    this.requestUpdate();
  }

  async _fetch_state() {
    try {
      const data = await get_browser_state();
      this._apply_state(data);
    } catch (error) {
      this._error = error && error.message ? error.message : String(error);
      this.requestUpdate();
    }
  }

  _apply_state(raw) {
    if (!raw || typeof raw !== 'object') return;

    const was_running = this._running;

    if (typeof raw.available === 'boolean') this._available = raw.available;
    if (typeof raw.running === 'boolean') this._running = raw.running;
    if ('browser' in raw) this._browser = typeof raw.browser === 'string' ? raw.browser : '';
    if ('executable' in raw) this._executable = typeof raw.executable === 'string' ? raw.executable : '';
    if ('profile' in raw) this._profile = typeof raw.profile === 'string' ? raw.profile : '';
    if ('port' in raw) this._port = raw.port ?? null;
    if ('title' in raw) this._title = typeof raw.title === 'string' ? raw.title : '';

    if ('url' in raw) {
      this._url = typeof raw.url === 'string' ? raw.url : '';
      if (this._url_input !== document.activeElement) this._url_draft = this._url;
    }

    if (Array.isArray(raw.tabs)) {
      this._tabs = raw.tabs
        .filter((tab) => tab && typeof tab.id === 'string')
        .map((tab) => ({
          id: tab.id,
          title: typeof tab.title === 'string' ? tab.title : '',
          url: typeof tab.url === 'string' ? tab.url : '',
          active: Boolean(tab.active),
        }));
    }

    if (raw.scroll && typeof raw.scroll === 'object') {
      this._scroll = {
        x: Number(raw.scroll.x) || 0,
        y: Number(raw.scroll.y) || 0,
        maxX: Number(raw.scroll.maxX) || 0,
        maxY: Number(raw.scroll.maxY) || 0,
      };
      this._scroll_known = true;
    } else if (raw.scroll === null) {
      this._scroll_known = false;
    }

    if ('activeTabId' in raw) {
      this._active_tab_id = typeof raw.activeTabId === 'string' ? raw.activeTabId : null;
    }

    if (raw.viewport && typeof raw.viewport === 'object') {
      this._viewport = {
        width: Number(raw.viewport.width) || 0,
        height: Number(raw.viewport.height) || 0,
        dpr: Number(raw.viewport.dpr) || 1,
      };
    }

    if (raw.error) this._error = String(raw.error);
    else if (raw.ok !== false) this._error = '';

    if (this._running && !was_running) {
      this._last_viewport_key = '';
      this._queue_viewport_send(0);
    }

    if (!this._running && was_running) {
      this._clear_frame();
      this._set_navigating(false);
      this._tabs = [];
      this._active_tab_id = null;
    }

    this.requestUpdate();
  }

  _connect_stream() {
    this._close_stream();
    clearTimeout(this._reconnect_timer);
    this._reconnect_timer = null;
    if (this._disconnected) return;

    this._stream_status = 'connecting';
    this.requestUpdate();

    let source;
    try {
      source = open_browser_stream();
    } catch (error) {
      this._stream_status = 'retrying';
      this.requestUpdate();
      this._schedule_reconnect();
      return;
    }

    this._stream = source;
    source.onopen = () => {
      this._last_viewport_key = '';
      this._reconnect_delay = RECONNECT_BASE_MS;
      this._stream_status = 'open';
      this.requestUpdate();
      this._fetch_state();
      this._queue_viewport_send(0);
    };
    source.onmessage = (event) => this._handle_stream_message(event);
    source.onerror = () => {
      if (this._stream !== source) return;
      this._close_stream();
      this._stream_status = 'retrying';
      this.requestUpdate();
      this._schedule_reconnect();
    };
  }

  _close_stream() {
    if (!this._stream) return;

    try {
      this._stream.close();
    } catch (error) {
      // The stream is already unusable; nothing else to do.
    }

    this._stream = null;
  }

  _schedule_reconnect() {
    if (this._disconnected || this._reconnect_timer) return;

    const delay = Math.round(this._reconnect_delay * (0.8 + Math.random() * 0.4));
    this._reconnect_delay = Math.min(Math.round(this._reconnect_delay * 1.7), RECONNECT_MAX_MS);
    this._reconnect_timer = setTimeout(() => {
      this._reconnect_timer = null;
      this._connect_stream();
    }, delay);
  }

  _on_visibility_change() {
    if (document.hidden) {
      this._close_stream();
      clearTimeout(this._reconnect_timer);
      this._reconnect_timer = null;
      this._stream_status = 'paused';
      this.requestUpdate();
      return;
    }

    if (!this._stream) this._connect_stream();
    this._fetch_state();
  }

  _handle_stream_message(event) {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch (error) {
      return;
    }

    if (!message || typeof message !== 'object') return;

    if (message.type === 'state') this._apply_state(message.state);
    else if (message.type === 'frame') this._handle_frame(message);
    else if (message.type === 'error') this._set_error(message.message || 'Browser stream error');
  }

  _handle_frame(message) {
    if (!message.data) return;
    if (document.hidden || !this.isConnected) return;
    if (
      typeof this.checkVisibility === 'function' &&
      !this.checkVisibility({ checkVisibilityCSS: true })
    ) {
      return;
    }
    const meta = message.meta && typeof message.meta === 'object' ? message.meta : {};
    this._enqueue_frame(message.data, meta);
  }

  _enqueue_frame(data, meta) {
    this._pending_frame = { data, meta };
    if (!this._decoding) this._decode_next();
  }

  async _decode_next() {
    const frame = this._pending_frame;
    if (!frame) return;
    this._pending_frame = null;
    this._decoding = true;

    try {
      const bitmap = await this._decode_frame(frame.data);
      if (this._disconnected || !this._running) {
        release_bitmap(bitmap);
        return;
      }

      this._frame_meta = frame.meta;
      if (this._last_bitmap) release_bitmap(this._last_bitmap);
      this._last_bitmap = bitmap;

      const was_ready = this._frame_ready;
      const was_navigating = this._navigating;
      this._frame_ready = true;

      if (this._navigating) {
        this._navigating = false;
        clearTimeout(this._navigating_timer);
        this._navigating_timer = null;
      }

      this._draw_bitmap(bitmap);
      if (!was_ready || was_navigating) this.requestUpdate();
    } catch (error) {
      // Ignore an unreadable frame; the next one will replace it.
    } finally {
      this._decoding = false;
      if (this._pending_frame) this._decode_next();
    }
  }

  async _decode_frame(data) {
    const blob = base64_to_blob(data);

    if (typeof createImageBitmap === 'function') {
      try {
        return await createImageBitmap(blob);
      } catch (error) {
        // Fall through to the Image element decoder.
      }
    }

    return load_image(blob);
  }

  _draw_bitmap(bitmap) {
    const canvas = this._canvas_context();
    if (!canvas) return;

    const { ctx, css_width, css_height, dpr } = canvas;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#14161b';
    ctx.fillRect(0, 0, css_width, css_height);

    const width = bitmap.width || bitmap.naturalWidth || 0;
    const height = bitmap.height || bitmap.naturalHeight || 0;
    if (!width || !height) {
      this._frame_rect = null;
      return;
    }

    const scale = Math.min(css_width / width, css_height / height);
    const draw_width = width * scale;
    const draw_height = height * scale;
    const x = (css_width - draw_width) / 2;
    const y = (css_height - draw_height) / 2;

    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(bitmap, x, y, draw_width, draw_height);

    this._frame_rect = {
      x,
      y,
      width: draw_width,
      height: draw_height,
      source_width: width,
      source_height: height,
    };
  }

  _clear_frame() {
    this._drop_frame();
    this._clear_canvas();
  }

  _drop_frame() {
    this._pending_frame = null;
    this._frame_meta = null;
    this._frame_rect = null;
    this._frame_ready = false;

    if (this._last_bitmap) {
      release_bitmap(this._last_bitmap);
      this._last_bitmap = null;
    }
  }

  _clear_canvas() {
    const canvas = this._canvas_context();
    if (!canvas) return;

    const { ctx, css_width, css_height, dpr } = canvas;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#14161b';
    ctx.fillRect(0, 0, css_width, css_height);
  }

  _canvas_context() {
    if (!this._canvas) return null;

    const rect = this._canvas.getBoundingClientRect();
    const css_width = Math.round(rect.width);
    const css_height = Math.round(rect.height);
    if (css_width < 2 || css_height < 2) return null;

    const dpr = Math.min(Math.max(window.devicePixelRatio || 1, 1), 2);
    const backing_width = Math.max(1, Math.round(css_width * dpr));
    const backing_height = Math.max(1, Math.round(css_height * dpr));

    if (this._canvas.width !== backing_width) this._canvas.width = backing_width;
    if (this._canvas.height !== backing_height) this._canvas.height = backing_height;

    const ctx = this._canvas.getContext('2d');
    if (!ctx) return null;

    return { ctx, css_width, css_height, dpr };
  }

  _cache_elements() {
    if (!this._canvas) this._canvas = this.querySelector('.browser-canvas');
    if (!this._viewport_el) this._viewport_el = this.querySelector('.browser-viewport');
    if (!this._stage_el) this._stage_el = this.querySelector('.browser-stage');
    if (!this._url_input) this._url_input = this.querySelector('.browser-url');
  }

  _setup_resize_observer() {
    if (!this._viewport_el) return;

    if (typeof ResizeObserver === 'function') {
      if (!this._resize_observer) {
        this._resize_observer = new ResizeObserver(() => this._on_viewport_resize());
        this._resize_observer.observe(this._viewport_el);
      }
      return;
    }

    if (!this._window_resize_bound) {
      window.addEventListener('resize', this._on_viewport_resize);
      this._window_resize_bound = true;
    }
  }

  _on_viewport_resize() {
    if (this._disconnected) return;

    if (this._last_bitmap && !this._redraw_scheduled) {
      this._redraw_scheduled = true;
      requestAnimationFrame(() => {
        this._redraw_scheduled = false;
        if (this._disconnected || !this._last_bitmap) return;
        this._draw_bitmap(this._last_bitmap);
      });
    }

    this._queue_viewport_send(180);
  }

  _queue_viewport_send(delay) {
    clearTimeout(this._viewport_send_timer);
    this._viewport_send_timer = setTimeout(() => {
      this._viewport_send_timer = null;
      this._send_viewport();
    }, Math.max(0, delay));
  }

  _send_viewport() {
    if (!this._running || this._disconnected || !this._viewport_el) return;

    const viewport = this._viewport_el;
    const scrollbar_height = Math.max(0, viewport.offsetHeight - viewport.clientHeight);
    const css_width = Math.round(viewport.clientWidth);
    const css_height = Math.round(viewport.clientHeight + scrollbar_height);
    if (css_width < VIEWPORT_MIN_PX || css_height < VIEWPORT_MIN_PX) return;

    const scale = Math.min(
      VIEWPORT_SCALE,
      MAX_VIEWPORT_WIDTH / css_width,
      MAX_VIEWPORT_HEIGHT / css_height,
    );
    const width = Math.max(320, Math.min(MAX_VIEWPORT_WIDTH, Math.round(css_width * scale)));
    const height = Math.max(240, Math.min(MAX_VIEWPORT_HEIGHT, Math.round(css_height * scale)));
    const dpr = Math.min(Math.max(window.devicePixelRatio || 1, 1), 2);
    const rounded_dpr = Number(dpr.toFixed(2));
    const key = `${width}x${height}@${rounded_dpr}`;
    if (key === this._last_viewport_key) return;

    set_browser_viewport(width, height, rounded_dpr)
      .then(() => {
        this._last_viewport_key = key;
        this._viewport = { width, height, dpr: rounded_dpr };
        this.requestUpdate();
      })
      .catch((error) => {
        if (error && error.status === 503) this._set_error(error);
      });
  }

  _bind_wheel() {
    if (this._wheel_bound || !this._canvas) return;
    this._canvas.addEventListener('wheel', this._on_wheel, { passive: false });
    this._wheel_bound = true;
  }

  _on_wheel(event) {
    if (!this._running) return;

    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      this._set_zoom(
        this._zoom * (event.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP),
        this._pointer_anchor(event),
      );
      return;
    }
    if (this._handoff_to_canvas(event)) return;
    event.preventDefault();

    const point = this._point_to_frame(event.clientX, event.clientY, true);
    if (!point) return;

    this._queue_input({
      kind: 'wheel',
      x: point.x,
      y: point.y,
      deltaX: event.deltaX,
      deltaY: event.deltaY,
    });
    this._advance_scroll_cache(event.deltaX, event.deltaY);
  }

  _handoff_to_canvas(event) {
    if (this._zoom <= 1 || !this._scroll_known) return false;

    const viewport = this._viewport_el;
    if (!viewport) return false;

    const horizontal = Math.abs(event.deltaX) > Math.abs(event.deltaY);
    const delta = horizontal ? event.deltaX : event.deltaY;
    if (!delta) return false;

    const scroll = this._scroll;
    const at_boundary = horizontal
      ? delta < 0
        ? scroll.x <= 1
        : scroll.x >= Math.max(0, scroll.maxX - 1)
      : delta < 0
        ? scroll.y <= 1
        : scroll.y >= Math.max(0, scroll.maxY - 1);
    if (!at_boundary) return false;

    // Let the browser scroll the zoomed canvas, then chain to the surrounding page.
    return true;
  }

  _advance_scroll_cache(deltaX, deltaY) {
    if (!this._scroll_known) return;

    this._scroll.x = clamp(this._scroll.x + (deltaX || 0), 0, this._scroll.maxX);
    this._scroll.y = clamp(this._scroll.y + (deltaY || 0), 0, this._scroll.maxY);
  }

  _on_pointerdown(event) {
    if (!this._running || event.button < 0) return;

    this._focus_canvas();
    const point = this._point_to_frame(event.clientX, event.clientY, false);
    if (!point) return;

    this._pointer_pressed = true;
    this._pointer_button = event.button;

    try {
      this._canvas.setPointerCapture(event.pointerId);
    } catch (error) {
      // Pointer capture is a nicety; ignore browsers that reject it.
    }

    this._queue_input({
      kind: 'mouse',
      type: 'mousePressed',
      x: point.x,
      y: point.y,
      button: button_name(event.button),
      buttons: event.buttons,
      clickCount: this._next_click_count(event.button),
    });
    event.preventDefault();
  }

  _on_pointermove(event) {
    if (!this._running) return;

    const point = this._point_to_frame(event.clientX, event.clientY, true);
    if (!point) return;

    this._queue_input({
      kind: 'mouse',
      type: 'mouseMoved',
      x: point.x,
      y: point.y,
      button: 'none',
      buttons: event.buttons,
      clickCount: 0,
    });
  }

  _on_pointerup(event) {
    if (!this._pointer_pressed) return;
    this._pointer_pressed = false;

    this._release_pointer(event.pointerId);
    const point = this._point_to_frame(event.clientX, event.clientY, true);
    if (!point) return;

    this._queue_input({
      kind: 'mouse',
      type: 'mouseReleased',
      x: point.x,
      y: point.y,
      button: button_name(event.button >= 0 ? event.button : this._pointer_button),
      buttons: event.buttons,
      clickCount: this._click_count,
    });
  }

  _on_pointercancel(event) {
    if (!this._pointer_pressed) return;
    this._pointer_pressed = false;

    this._release_pointer(event.pointerId);
    const point = this._point_to_frame(event.clientX, event.clientY, true);
    if (!point) return;

    this._queue_input({
      kind: 'mouse',
      type: 'mouseReleased',
      x: point.x,
      y: point.y,
      button: button_name(this._pointer_button),
      buttons: 0,
      clickCount: this._click_count,
    });
  }

  _on_contextmenu(event) {
    event.preventDefault();
  }

  _on_canvas_keydown(event) {
    if (event.key === 'Escape') event.stopPropagation();
    if (event.isComposing) return;
    if (!this._running) return;

    const key = event.key;
    const has_command = event.ctrlKey || event.metaKey || event.altKey;
    const is_special = SPECIAL_KEYS.has(key);
    const is_printable = key.length === 1;

    if (!is_special && !is_printable && !has_command) return;

    event.preventDefault();
    const code = event.code || '';
    const id = code || key;
    const held = { key, code, keyCode: event.keyCode || 0 };
    if (!this._held_keys.has(id)) this._held_keys.set(id, held);

    this._queue_input({
      kind: 'key',
      type: has_command ? 'rawKeyDown' : 'keyDown',
      key,
      code,
      modifiers: this._modifiers(event),
      text: has_command ? '' : is_printable ? key : '',
      windowsVirtualKeyCode: held.keyCode,
    });
  }

  _on_canvas_keyup(event) {
    if (event.key === 'Escape') event.stopPropagation();

    const id = event.code || event.key;
    const held = this._held_keys.get(id);
    if (!held) return;

    this._held_keys.delete(id);
    if (!this._running) return;

    event.preventDefault();
    this._queue_input({
      kind: 'key',
      type: 'keyUp',
      key: event.key,
      code: event.code || held.code,
      modifiers: this._modifiers(event),
      text: '',
      windowsVirtualKeyCode: event.keyCode || held.keyCode || 0,
    });
  }

  _on_canvas_blur() {
    for (const held of this._held_keys.values()) {
      this._queue_input({
        kind: 'key',
        type: 'keyUp',
        key: held.key,
        code: held.code,
        modifiers: 0,
        text: held.key.length === 1 ? held.key : '',
      });
    }

    this._held_keys.clear();
  }

  _on_paste(event) {
    const text = event.clipboardData ? event.clipboardData.getData('text') : '';
    if (!text) return;

    event.preventDefault();
    if (!this._running) return;
    this._queue_input({ kind: 'text', text });
  }

  _modifiers(event) {
    return (event.altKey ? 1 : 0)
      | (event.ctrlKey ? 2 : 0)
      | (event.metaKey ? 4 : 0)
      | (event.shiftKey ? 8 : 0);
  }

  _next_click_count(button) {
    const now = performance.now();
    if (button === this._last_click_button && now - this._last_click_time < 450) {
      this._click_count = Math.min(this._click_count + 1, 3);
    } else {
      this._click_count = 1;
    }

    this._last_click_time = now;
    this._last_click_button = button;
    return this._click_count;
  }

  _point_to_frame(client_x, client_y, clamp_to_content) {
    if (!this._canvas) return null;

    const rect = this._canvas.getBoundingClientRect();
    const content = this._frame_rect;
    let nx;
    let ny;

    if (content) {
      nx = (client_x - rect.left - content.x) / Math.max(content.width, 1);
      ny = (client_y - rect.top - content.y) / Math.max(content.height, 1);
    } else {
      nx = (client_x - rect.left) / Math.max(rect.width, 1);
      ny = (client_y - rect.top) / Math.max(rect.height, 1);
    }

    if (!clamp_to_content && (nx < 0 || nx > 1 || ny < 0 || ny > 1)) return null;

    const space = this._input_space();
    const width = Math.max(1, Math.round(space.width));
    const height = Math.max(1, Math.round(space.height));

    return {
      x: Math.min(width - 1, Math.round(clamp(nx, 0, 1) * width)),
      y: Math.min(height - 1, Math.round(clamp(ny, 0, 1) * height)),
    };
  }

  _input_space() {
    const viewport = this._viewport;
    if (viewport && viewport.width > 0 && viewport.height > 0) return viewport;

    const meta = this._frame_meta || {};
    const scale = Number(meta.deviceScaleFactor) > 0 ? Number(meta.deviceScaleFactor) : 1;
    const width = Number(meta.deviceWidth) || 0;
    const height = Number(meta.deviceHeight) || 0;
    if (width > 0 && height > 0) return { width: width / scale, height: height / scale };

    const content = this._frame_rect;
    if (content && content.source_width > 0 && content.source_height > 0) {
      return { width: content.source_width, height: content.source_height };
    }

    return { width: 1, height: 1 };
  }

  _focus_canvas() {
    if (!this._canvas) return;

    try {
      this._canvas.focus({ preventScroll: true });
    } catch (error) {
      this._canvas.focus();
    }
  }

  _release_pointer(pointer_id) {
    if (!this._canvas) return;

    try {
      if (this._canvas.hasPointerCapture(pointer_id)) {
        this._canvas.releasePointerCapture(pointer_id);
      }
    } catch (error) {
      // Capture may already have been released.
    }
  }

  _queue_input(event) {
    if (!this._running || this._disconnected) return;

    if (event.kind === 'mouse' && event.type === 'mouseMoved') {
      const last = this._input_queue[this._input_queue.length - 1];
      if (last && last.kind === 'mouse' && last.type === 'mouseMoved') {
        this._input_queue[this._input_queue.length - 1] = event;
      } else {
        this._input_queue.push(event);
      }
    } else {
      this._input_queue.push(event);
    }

    if (this._input_queue.length > INPUT_QUEUE_LIMIT) {
      const move_index = this._input_queue.findIndex(
        (item) => item.kind === 'mouse' && item.type === 'mouseMoved',
      );
      if (move_index !== -1) this._input_queue.splice(move_index, 1);
    }

    this._flush_input();
  }

  async _flush_input() {
    if (this._input_flushing) return;
    this._input_flushing = true;

    while (this._input_queue.length) {
      const event = this._input_queue.shift();

      try {
        await send_browser_input(event);
      } catch (error) {
        if (error && error.status === 503) {
          this._set_error(error);
          this._input_queue.length = 0;
          break;
        }
      }
    }

    this._input_flushing = false;
  }

  _set_navigating(value) {
    this._navigating = Boolean(value);
    clearTimeout(this._navigating_timer);
    this._navigating_timer = null;

    if (this._navigating) {
      this._navigating_timer = setTimeout(() => {
        this._navigating = false;
        this._navigating_timer = null;
        this.requestUpdate();
      }, 15000);
    }

    this.requestUpdate();
  }

  _set_error(error) {
    this._error = error && error.message ? error.message : String(error || 'Unknown browser error');
    this.requestUpdate();
  }
}

customElements.define('browser-panel', BrowserPanel);

function tab_label(tab) {
  const title = String(tab?.title || '').trim();
  if (title) return title;

  const url = String(tab?.url || '').trim();
  if (!url) return tab?.id || 'Tab';

  try {
    return new URL(url).hostname || url;
  } catch (error) {
    return url;
  }
}

function navigation_url(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  if (/^(?:https?|about|file|chrome|data):/i.test(text)) return text;

  const host = text.split(/[/?#]/, 1)[0];
  const looks_like_host =
    /^(?:localhost|\d{1,3}(?:\.\d{1,3}){3}|\[[0-9a-f:]+\])(?::\d+)?$/i.test(host) ||
    /^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}(?::\d+)?$/i.test(host);

  if (!/\s/.test(text) && looks_like_host) return text;

  return `https://www.google.com/search?q=${encodeURIComponent(text)}`;
}

function base64_to_blob(data) {
  const comma = data.indexOf(',');
  const encoded = data.startsWith('data:') && comma !== -1 ? data.slice(comma + 1) : data;
  const binary = atob(encoded.replace(/\s+/g, ''));
  const bytes = new Uint8Array(binary.length);

  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }

  return new Blob([bytes], { type: 'image/jpeg' });
}

function load_image(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const image = new Image();
    image.decoding = 'async';
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('Frame decode failed'));
    };
    image.src = url;
  });
}

function release_bitmap(bitmap) {
  if (bitmap && typeof bitmap.close === 'function') bitmap.close();
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function button_name(button) {
  switch (button) {
    case 1:
      return 'middle';
    case 2:
      return 'right';
    case 3:
      return 'back';
    case 4:
      return 'forward';
    default:
      return 'left';
  }
}
