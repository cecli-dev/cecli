/** Read the desktop authentication token without requiring the inline script. */
export function get_desktop_token() {
  if (typeof document !== 'undefined') {
    const meta = document.querySelector('meta[name="cecli-token"]');
    const value = meta?.getAttribute('content');
    if (value) return value;
  }

  return typeof window !== 'undefined' ? window.__CECLI_TOKEN__ || '' : '';
}