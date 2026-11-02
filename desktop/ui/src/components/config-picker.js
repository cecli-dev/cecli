import { LitElement, html, nothing } from 'lit';

import { session } from '../core/session.js';

export class ConfigPicker extends LitElement {
  static properties = {
    option: { attribute: false },
  };

  createRenderRoot() {
    return this;
  }

  updated() {
    const select = this.querySelector('select');
    const value = this.option?.currentValue;
    if (select && value !== undefined && value !== null && select.value !== String(value)) {
      select.value = String(value);
    }
  }

  render() {
    const option = this.option;
    const choices = Array.isArray(option.options) ? option.options : [];

    return html`
      <label class="picker" title=${option.name || option.id}>
        <span class="picker-label">${option.name || option.id}</span>
        <select
          class="select picker-select"
          data-config-id=${option.id}
          aria-label=${option.name || option.id}
          @change=${this._on_change}
        >
          ${choices.map((item) => this._render_choice(item, option.currentValue))}
        </select>
      </label>
    `;
  }

  _render_choice(item, current_value) {
    if (!item) return nothing;

    if (Array.isArray(item.options)) {
      return html`
        <optgroup label=${item.name || item.group || ''}>
          ${item.options.map((choice) => this._render_option(choice, current_value))}
        </optgroup>
      `;
    }

    return this._render_option(item, current_value);
  }

  _render_option(choice, current_value) {
    const value = String(choice.value);
    const selected =
      current_value !== undefined &&
      current_value !== null &&
      String(current_value) === value;

    return html`
      <option value=${value} ?selected=${selected} title=${choice.description || nothing}>
        ${choice.name || value}
      </option>
    `;
  }

  async _on_change(event) {
    const select = event.currentTarget;
    const previous = this.option.currentValue;
    const ok = await session.change_config(this.option.id, select.value);

    if (!ok && previous !== null && previous !== undefined) {
      select.value = String(previous);
    }
  }
}

customElements.define('config-picker', ConfigPicker);
