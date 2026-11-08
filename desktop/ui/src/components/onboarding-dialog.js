import { LitElement, html, nothing } from 'lit';

import { get_copilot_status, get_onboarding_providers, post_json } from '../core/api.js';
import { session } from '../core/session.js';

const COPILOT_SLUG = 'github_copilot';

export class OnboardingDialog extends LitElement {
  static properties = {
    open: { type: Boolean },
  };

  constructor() {
    super();
    this.open = false;
    this._step = 'provider';
    this._providers = [];
    this._provider = null;
    this._key_values = {};
    this._models = [];
    this._query = '';
    this._copilot = null;
    this._login = null;
    this._loading = false;
    this._busy = false;
    this._error = '';
    this._poll_timer = null;
  }

  createRenderRoot() {
    return this;
  }

  willUpdate(changed) {
    if (changed.has('open') && this.open) {
      this._reset();
      if (!this._providers.length) this._load_providers();
    }

  }
  disconnectedCallback() {
    super.disconnectedCallback();
    this._stop_polling();
  }

  render() {
    if (!this.open) return nothing;

    return html`
      <div class="modal-backdrop" @click=${this._on_backdrop}>
        <div
          class="modal-card modal-card--wide onboarding-card"
          role="dialog"
          aria-modal="true"
          aria-labelledby="onboarding-title"
          @click=${this._stop}
        >
          <h2 id="onboarding-title">${this._title()}</h2>
          ${this._render_step()}
          ${this._error ? html`<p class="modal-error">${this._error}</p>` : nothing}
          <div class="modal-actions">
            ${this._step === 'provider'
              ? nothing
              : html`<button type="button" class="modal-btn" @click=${this._back}>Back</button>`}
            <button type="button" class="modal-btn" @click=${this._close}>Cancel</button>
          </div>
        </div>
      </div>
    `;
  }

  _title() {
    if (this._step === 'configure') return `Connect ${this._provider?.display_name || 'provider'}`;
    if (this._step === 'copilot') return 'Connect GitHub Copilot';
    if (this._step === 'models') return 'Choose a default model';
    return 'Set up cecli';
  }

  _render_step() {
    if (this._loading) return html`<p class="modal-empty">Loading\u2026</p>`;
    if (this._step === 'configure') return this._render_keys();
    if (this._step === 'copilot') return this._render_copilot();
    if (this._step === 'models') return this._render_models();
    return this._render_providers();
  }

  _render_providers() {
    return html`
      <p class="modal-hint">Pick a provider. Keys are saved to ~/.cecli/.env; the model goes to conf.yml.</p>
      <ul class="registry-modal-list onboarding-list">
        ${this._providers.map(
          (provider) => html`
            <li>
              <button
                type="button"
                class="registry-modal-row onboarding-row"
                @click=${() => this._choose_provider(provider)}
              >
                <span class="registry-modal-name">${provider.display_name}</span>
                ${provider.slug === COPILOT_SLUG
                  ? html`<span class="model-group">OAuth</span>`
                  : nothing}
                ${provider.configured
                  ? html`<span class="registry-tag">configured</span>`
                  : html`<span class="model-group">${provider.api_key_env.join(', ') || 'no key'}</span>`}
              </button>
            </li>
          `,
        )}
      </ul>
    `;
  }

  _render_keys() {
    const env_names = this._provider?.api_key_env || [];

    return html`
      <p class="modal-hint">Enter the provider API key values.</p>
      ${env_names.map(
        (name) => html`
          <label class="modal-field">
            <span>${name}</span>
            <input
              type="password"
              .value=${this._key_values[name] || ''}
              placeholder=${name}
              @input=${(event) => this._on_key(name, event)}
            />
          </label>
        `,
      )}
      <div class="modal-actions">
        <button
          type="button"
          class="modal-btn modal-btn--primary"
          ?disabled=${this._busy}
          @click=${this._continue_keys}
        >
          Continue
        </button>
      </div>
    `;
  }

  _render_copilot() {
    const login = this._login || this._copilot?.login || {};
    const pending = login.state === 'pending' || login.state === 'configured';

    if (pending && login.verification_uri) {
      return html`
        <p class="modal-hint">Open GitHub and enter this code:</p>
        <p class="onboarding-code">${login.user_code || '\u2026'}</p>
        <p class="modal-hint">
          <a href=${login.verification_uri} target="_blank" rel="noreferrer">
            ${login.verification_uri}
          </a>
        </p>
        <p class="modal-hint">Waiting for authorization\u2026</p>
      `;
    }

    if (login.state === 'error' || login.state === 'expired') {
      return html`
        <p class="modal-error">${login.error || 'GitHub authorization failed'}</p>
        <div class="modal-actions">
          <button type="button" class="modal-btn modal-btn--primary" @click=${this._start_copilot_login}>
            Try again
          </button>
        </div>
      `;
    }

    return html`
      <p class="modal-hint">
        GitHub Copilot uses OAuth, not an API key. Sign in once and its models become available.
      </p>
      <div class="modal-actions">
        <button
          type="button"
          class="modal-btn modal-btn--primary"
          ?disabled=${this._busy}
          @click=${this._start_copilot_login}
        >
          Sign in with GitHub
        </button>
      </div>
    `;
  }

  _render_models() {
    const items = this._filtered_models();

    return html`
      <input
        class="model-search"
        type="search"
        .value=${this._query}
        placeholder="Search models\u2026"
        aria-label="Search models"
        @input=${this._on_query}
      />
      <p class="modal-hint">${items.length} model${items.length === 1 ? '' : 's'}</p>
      ${items.length
        ? html`
            <ul class="registry-modal-list model-list onboarding-list">
              ${items.map(
                (model) => html`
                  <li>
                    <button
                      type="button"
                      class="registry-modal-row model-row"
                      ?disabled=${this._busy}
                      @click=${() => this._select_model(model)}
                    >
                      <span class="registry-modal-name" title=${model}>${model}</span>
                    </button>
                  </li>
                `,
              )}
            </ul>
          `
        : html`
            <p class="modal-empty">No models were discovered.</p>
            <label class="modal-field">
              <span>Model name</span>
              <input
                type="text"
                placeholder="provider/model-name"
                @keydown=${this._on_manual_model}
              />
            </label>
            <p class="modal-hint">Type a model name and press Enter.</p>
          `}
    `;
  }

  async _load_providers() {
    this._loading = true;
    this._error = '';
    this.requestUpdate();
    try {
      const payload = await get_onboarding_providers();
      this._providers = payload.providers || [];
    } catch (error) {
      this._error = error.message;
    } finally {
      this._loading = false;
      this.requestUpdate();
    }
  }

  async _choose_provider(provider) {
    this._provider = provider;
    this._key_values = {};
    this._error = '';
    if (provider.slug === COPILOT_SLUG) {
      await this._open_copilot();
      return;
    }
    if (provider.requires_key && !provider.configured) {
      this._step = 'configure';
      this.requestUpdate();
      return;
    }
    await this._load_models();
  }

  async _open_copilot() {
    this._loading = true;
    this._step = 'copilot';
    this.requestUpdate();
    try {
      this._copilot = await get_copilot_status();
      this._login = this._copilot.login || null;
      if (this._copilot.configured) {
        await this._load_models();
        return;
      }
    } catch (error) {
      this._error = error.message;
    } finally {
      this._loading = false;
      this.requestUpdate();
    }
  }

  async _start_copilot_login() {
    this._busy = true;
    this._error = '';
    this.requestUpdate();
    try {
      const result = await post_json('/api/onboarding/copilot/login', {});
      this._login = result;
      this._start_polling();
    } catch (error) {
      this._error = error.message;
    } finally {
      this._busy = false;
      this.requestUpdate();
    }
  }

  _start_polling() {
    this._stop_polling();
    this._poll_timer = setInterval(() => this._poll_copilot(), 2500);
  }

  _stop_polling() {
    if (this._poll_timer) clearInterval(this._poll_timer);
    this._poll_timer = null;
  }

  async _poll_copilot() {
    try {
      const status = await get_copilot_status();
      this._copilot = status;
      this._login = status.login || this._login;
      if (status.configured) {
        this._stop_polling();
        await this._load_models();
        return;
      }
      if (this._login && ['error', 'expired'].includes(this._login.state)) this._stop_polling();
      this.requestUpdate();
    } catch (error) {
      this._stop_polling();
      this._error = error.message;
      this.requestUpdate();
    }
  }

  _on_key(name, event) {
    this._key_values[name] = event.target.value;
  }

  async _continue_keys() {
    const missing = (this._provider.api_key_env || []).filter(
      (name) => !String(this._key_values[name] || '').trim(),
    );
    if (missing.length) {
      this._error = `Enter ${missing.join(', ')}`;
      this.requestUpdate();
      return;
    }
    await this._load_models();
  }

  async _load_models() {
    this._loading = true;
    this._error = '';
    this.requestUpdate();
    try {
      const payload = await get_onboarding_providers(this._provider.slug);
      this._models = payload.models || [];
      this._step = 'models';
      this._query = '';
    } catch (error) {
      this._error = error.message;
    } finally {
      this._loading = false;
      this.requestUpdate();
    }
  }

  _filtered_models() {
    const query = this._query.trim().toLowerCase();
    if (!query) return this._models;
    return this._models.filter((model) => model.toLowerCase().includes(query));
  }

  _on_query(event) {
    this._query = event.target.value;
    this.requestUpdate();
  }

  async _select_model(model) {
    if (this._busy || !model) return;
    this._busy = true;
    this._error = '';
    this.requestUpdate();
    try {
      await session.configure_provider({
        provider: this._provider.slug,
        model,
        api_keys: this._key_values,
      });
      this._close();
    } catch (error) {
      this._error = error.message;
    } finally {
      this._busy = false;
      this.requestUpdate();
    }
  }

  _on_manual_model(event) {
    if (event.key !== 'Enter' || event.isComposing) return;
    const value = event.target.value.trim();
    if (value) this._select_model(value);
  }

  _back() {
    this._error = '';
    this._stop_polling();
    this._step = 'provider';
    this._provider = null;
    this._models = [];
    this._login = null;
    this.requestUpdate();
  }

  _reset() {
    this._step = 'provider';
    this._provider = null;
    this._key_values = {};
    this._models = [];
    this._query = '';
    this._copilot = null;
    this._login = null;
    this._error = '';
    this._busy = false;
  }

  _on_backdrop() {
    if (!this._busy) this._close();
  }

  _stop(event) {
    event.stopPropagation();
  }

  _close() {
    this._stop_polling();
    this.open = false;
    session.close_onboarding();
    this.dispatchEvent(new CustomEvent('close', { bubbles: true, composed: true }));
  }
}

customElements.define('onboarding-dialog', OnboardingDialog);