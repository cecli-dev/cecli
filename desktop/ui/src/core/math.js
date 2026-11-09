/** KaTeX-backed math rendering with safe defaults. */

import katex from 'katex';

/** Render TeX source to safe KaTeX HTML, or escaped text on unexpected errors. */
export function render_math_html(source, { display_mode = false } = {}) {
  const text = decode_math_entities(String(source === undefined || source === null ? '' : source)).trim();

  try {
    return katex.renderToString(text, {
      displayMode: Boolean(display_mode),
      throwOnError: false,
      strict: false,
      trust: false,
      output: 'htmlAndMathml',
      errorColor: '#d93a4a',
    });
  } catch (error) {
    return `<span class="math-error">${escape_math_text(text)}</span>`;
  }
}

/** Undo the entities markdown escaping added so KaTeX sees raw TeX. */
function decode_math_entities(value) {
  return value
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, '&');
}

/** Escape fallback text; KaTeX normally handles this itself. */
function escape_math_text(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
