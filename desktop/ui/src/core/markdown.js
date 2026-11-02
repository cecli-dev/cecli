/**
 * Safe markdown subset for model output.
 * Every buffer is escaped before any formatting is applied, and links are
 * restricted to http(s) URLs.
 */

/** Escape HTML entities before any formatting is applied. */
export function escape_html(value) {
  return String(value === undefined || value === null ? '' : value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/** Convert a plain-text markdown buffer into safe HTML. */
export function markdown_to_html(text) {
  const lines = escape_html(text).split('\n');
  const html = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = /^```([\w+#.-]*)\s*$/.exec(line.trim());
    if (fence) {
      const language = fence[1] || '';
      const code = [];
      index += 1;

      while (index < lines.length && !/^```\s*$/.test(lines[index].trim())) {
        code.push(lines[index]);
        index += 1;
      }

      if (index < lines.length) index += 1;
      html.push(render_code_block_html(code.join('\n'), language));
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      html.push(`<h${level}>${inline_to_html(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      html.push('<hr>');
      index += 1;
      continue;
    }

    if (/^\s*&gt;\s?/.test(line)) {
      const quoted = [];

      while (index < lines.length && /^\s*&gt;\s?/.test(lines[index])) {
        quoted.push(lines[index].replace(/^\s*&gt;\s?/, ''));
        index += 1;
      }

      html.push(`<blockquote>${inline_to_html(quoted.join('\n')).replace(/\n/g, '<br>')}</blockquote>`);
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items = [];

      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(inline_to_html(lines[index].replace(/^\s*[-*+]\s+/, '')));
        index += 1;
      }

      html.push(`<ul>${items.map((item) => `<li>${item}</li>`).join('')}</ul>`);
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = [];

      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        items.push(inline_to_html(lines[index].replace(/^\s*\d+[.)]\s+/, '')));
        index += 1;
      }

      html.push(`<ol>${items.map((item) => `<li>${item}</li>`).join('')}</ol>`);
      continue;
    }

    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !starts_block_line(lines[index])) {
      paragraph.push(lines[index]);
      index += 1;
    }

    if (paragraph.length) {
      html.push(`<p>${inline_to_html(paragraph.join('\n')).replace(/\n/g, '<br>')}</p>`);
    } else {
      index += 1;
    }
  }

  return html.join('');
}

/** True when a line begins a non-paragraph block. */
function starts_block_line(line) {
  return (
    /^```/.test(line.trim()) ||
    /^#{1,3}\s+/.test(line) ||
    /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line) ||
    /^\s*&gt;\s?/.test(line) ||
    /^\s*[-*+]\s+/.test(line) ||
    /^\s*\d+[.)]\s+/.test(line)
  );
}

/** Render a fenced code block with a language label and copy control. */
function render_code_block_html(code, language) {
  const label = language ? escape_html(language) : 'text';
  return `<div class="code-block"><div class="code-head"><span class="code-lang">${label}</span><button type="button" class="code-copy" aria-label="Copy code">Copy</button></div><pre><code>${code}</code></pre></div>`;
}

/** Convert inline markdown within already-escaped text. */
function inline_to_html(text) {
  const parts = text.split(/(`[^`\n]+`)/g);

  return parts
    .map((part, index) => {
      if (index % 2 === 1) return `<code>${part.slice(1, -1)}</code>`;
      return format_inline_text(part);
    })
    .join('');
}

/** Apply links, emphasis, strikethrough while protecting link URLs. */
function format_inline_text(text) {
  const links = [];

  let output = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, (match, label, url) => {
    links.push({ label, url });
    return `\u0000link${links.length - 1}\u0000`;
  });

  output = format_emphasis(output);

  output = output.replace(/\u0000link(\d+)\u0000/g, (match, index) => {
    const link = links[Number(index)];
    if (!link) return '';
    return `<a href="${link.url}" target="_blank" rel="noopener noreferrer">${format_emphasis(link.label)}</a>`;
  });

  return output;
}

/** Bold, italic, and strikethrough on escaped text. */
function format_emphasis(text) {
  return text
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/__([^_]+)__/g, '<strong>$1</strong>')
    .replace(/~~([^~]+)~~/g, '<del>$1</del>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
    .replace(/(^|[^\w])_([^_\n]+)_(?!\w)/g, '$1<em>$2</em>');
}
