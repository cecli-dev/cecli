import { get_json, post_json } from './api.js';

const THEME_STORAGE_KEY = 'cecli.theme';
const THEME_ENDPOINT = '/api/theme';
const DARK = 'dark';
const LIGHT = 'light';

const listeners = new Set();

let current_theme = read_dom_theme();
let initialized = false;

/** Apply the persisted or system theme once at startup. */
export function init_theme() {
  if (initialized) return current_theme;
  initialized = true;

  const boot_theme = read_boot_theme();
  apply_theme(boot_theme || read_stored_theme() || system_theme());
  if (boot_theme) write_stored_theme(boot_theme);
  watch_system_theme();
  refresh_remote_theme();
  return current_theme;
}

/** Return the active theme name. */
export function get_theme() {
  return current_theme;
}

/** Set the theme and persist it unless explicitly disabled. */
export function set_theme(theme, { persist = true } = {}) {
  const next = normalize_theme(theme);
  if (persist) {
    write_stored_theme(next);
    write_remote_theme(next);
  }
  apply_theme(next);
  return current_theme;
}

/** Flip between light and dark. */
export function toggle_theme() {
  return set_theme(current_theme === DARK ? LIGHT : DARK);
}

/** Subscribe to theme changes; returns an unsubscribe function. */
export function subscribe_theme(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Read a themed CSS color for canvas and terminal APIs. */
export function read_theme_color(name, fallback = '') {
  if (typeof window === 'undefined') return fallback;

  const value = getComputedStyle(document.body).getPropertyValue(name).trim();
  return value || fallback;
}

function apply_theme(theme) {
  const next = normalize_theme(theme);
  const changed = next !== current_theme;
  current_theme = next;

  if (typeof document !== 'undefined') {
    const is_dark = next === DARK;
    document.body.classList.toggle(DARK, is_dark);
    document.body.dataset.theme = next;
    document.documentElement.style.colorScheme = next;
    update_theme_color_meta(next);
  }

  if (changed) {
    for (const listener of listeners) listener(current_theme);
  }
}

function watch_system_theme() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;

  const query = window.matchMedia('(prefers-color-scheme: dark)');
  const onChange = (event) => {
    if (read_stored_theme()) return;
    apply_theme(event.matches ? DARK : LIGHT);
  };

  if (typeof query.addEventListener === 'function') {
    query.addEventListener('change', onChange);
  } else if (typeof query.addListener === 'function') {
    query.addListener(onChange);
  }
}

function update_theme_color_meta(theme) {
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', theme === DARK ? '#303446' : '#eff1f5');
}

function system_theme() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return LIGHT;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? DARK : LIGHT;
}

function read_dom_theme() {
  if (typeof document === 'undefined') return LIGHT;
  return document.body?.classList.contains(DARK) ? DARK : LIGHT;
}

function read_stored_theme() {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return normalize_known_theme(value);
  } catch (error) {
    return null;
  }
}

function write_stored_theme(theme) {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch (error) {
    // Storage can be unavailable in restricted webviews; the class still applies.
  }
}

function read_boot_theme() {
  if (typeof window === 'undefined') return null;
  return normalize_known_theme(window.__CECLI_THEME__);
}


async function refresh_remote_theme() {
  try {
    const data = await get_json(THEME_ENDPOINT);
    const theme = normalize_known_theme(data?.theme);
    if (!theme) return;

    write_stored_theme(theme);
    apply_theme(theme);
  } catch (error) {
    // The backend is optional; the cached or system theme remains active.
  }
}


function write_remote_theme(theme) {
  post_json(THEME_ENDPOINT, { theme }).catch(() => {
    // Persistence is best-effort; localStorage still records the choice.
  });
}


function normalize_known_theme(theme) {
  return theme === DARK || theme === LIGHT ? theme : null;
}


function normalize_theme(theme) {
  return theme === DARK ? DARK : LIGHT;
}
