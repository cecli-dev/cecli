/**
 * Safe markdown subset for model output.
 * Every buffer is escaped before any formatting is applied, and links are
 * restricted to http(s) URLs.
 */

import { render_math_html } from './math.js';

const INLINE_MATH_PATTERN = /(\$\$[^$\n]+\$\$|\$[^$\n]+\$|\\\([^\n]+?\\\))/g;

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
  return markdown_blocks(text)
    .map((block) => block.render())
    .join('');
}

/**
 * Parse the top-level blocks of `text` without rendering them yet.
 *
 * Each block keeps its escaped source and a lazy `render` callback, so a streaming view can
 * reuse the HTML of blocks whose source has already settled.
 */
export function markdown_blocks(text) {
  const lines = escape_html(text).split('\n');
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (!line.trim()) {
      index += 1;
      continue;
    }

    const start = index;
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
      push_block(blocks, lines, start, index, () => render_code_block_html(code.join('\n'), language));
      continue;
    }

    const math_closer = math_block_closer(line);
    if (math_closer) {
      const math_lines = [];
      let closed = false;

      index += 1;

      while (index < lines.length) {
        if (lines[index].trim() === math_closer) {
          closed = true;
          index += 1;
          break;
        }

        math_lines.push(lines[index]);
        index += 1;
      }

      push_block(blocks, lines, start, index, () => render_math_block_html(math_lines.join('\n'), !closed));
      continue;
    }

    const single_line_math = single_line_display_math(line);
    if (single_line_math) {
      push_block(blocks, lines, start, index + 1, () => render_math_block_html(single_line_math[1], false));
      index += 1;
      continue;
    }

    if (is_table_start(lines, index)) {
      const header_cells = split_table_row(lines[index]);
      const delimiter_cells = split_table_row(lines[index + 1]);
      const alignments = delimiter_cells.map(parse_table_alignment);
      const body_rows = [];

      index += 2;

      while (
        index < lines.length &&
        lines[index].trim() &&
        has_unescaped_pipe(lines[index]) &&
        !starts_block_line(lines, index)
      ) {
        body_rows.push(normalize_table_row(split_table_row(lines[index]), header_cells.length));
        index += 1;
      }

      push_block(blocks, lines, start, index, () => render_table_html(header_cells, alignments, body_rows));
      continue;
    }

    const heading = /^(#{1,3})\s+(.+)$/.exec(line);
    if (heading) {
      const level = heading[1].length;
      push_block(blocks, lines, start, index + 1, () => `<h${level}>${inline_to_html(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }

    if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      push_block(blocks, lines, start, index + 1, () => '<hr>');
      index += 1;
      continue;
    }

    if (/^\s*&gt;\s?/.test(line)) {
      const quoted = [];

      while (index < lines.length && /^\s*&gt;\s?/.test(lines[index])) {
        quoted.push(lines[index].replace(/^\s*&gt;\s?/, ''));
        index += 1;
      }

      push_block(blocks, lines, start, index, () => `<blockquote>${inline_to_html(quoted.join('\n')).replace(/\n/g, '<br>')}</blockquote>`);
      continue;
    }

    if (/^\s*[-*+]\s+/.test(line)) {
      const items = [];

      while (index < lines.length && /^\s*[-*+]\s+/.test(lines[index])) {
        items.push(inline_to_html(lines[index].replace(/^\s*[-*+]\s+/, '')));
        index += 1;
      }

      push_block(blocks, lines, start, index, () => `<ul>${items.map((item) => `<li>${item}</li>`).join('')}</ul>`);
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = [];

      while (index < lines.length && /^\s*\d+[.)]\s+/.test(lines[index])) {
        items.push(inline_to_html(lines[index].replace(/^\s*\d+[.)]\s+/, '')));
        index += 1;
      }

      push_block(blocks, lines, start, index, () => `<ol>${items.map((item) => `<li>${item}</li>`).join('')}</ol>`);
      continue;
    }

    const paragraph = [];
    while (index < lines.length && lines[index].trim() && !starts_block_line(lines, index)) {
      paragraph.push(lines[index]);
      index += 1;
    }

    if (paragraph.length) {
      push_block(blocks, lines, start, index, () => `<p>${inline_to_html(paragraph.join('\n')).replace(/\n/g, '<br>')}</p>`);
    } else {
      index += 1;
    }
  }

  return blocks;
}

/**
 * Render growing markdown incrementally; blocks whose source is unchanged keep their HTML.
 */
export class MarkdownStreamRenderer {
  constructor() {
    this._blocks = [];
  }

  render(text) {
    const blocks = markdown_blocks(text).map((block, index) => {
      const cached = this._blocks[index];
      if (cached !== undefined && cached.source === block.source) return cached;

      return { source: block.source, html: block.render() };
    });

    this._blocks = blocks;
    return blocks;
  }

  reset() {
    this._blocks = [];
  }
}

/** Record one parsed block with its escaped source for later cache checks. */
function push_block(blocks, lines, start, end, render) {
  blocks.push({ source: lines.slice(start, end).join('\n'), render });
}

/** True when the line at `index` begins a non-paragraph block. */
function starts_block_line(lines, index) {
  const line = lines[index];

  return (
    /^```/.test(line.trim()) ||
    math_block_closer(line) !== null ||
    single_line_display_math(line) !== null ||
    /^#{1,3}\s+/.test(line) ||
    /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line) ||
    /^\s*&gt;\s?/.test(line) ||
    /^\s*[-*+]\s+/.test(line) ||
    /^\s*\d+[.)]\s+/.test(line) ||
    is_table_start(lines, index)
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
      return format_inline_math(part);
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

/** Render a display-math block with escaped source. */
function render_math_block_html(source, pending) {
  const class_name = pending ? 'math-block math-block-pending' : 'math-block';
  return `<div class="${class_name}" role="math"><div class="math-content">${render_math_html(source, { display_mode: true })}</div></div>`;
}


/** Render inline math while leaving currency (`$5`) untouched. */
function format_inline_math(text) {
  const parts = text.split(INLINE_MATH_PATTERN);

  if (parts.length === 1) return format_inline_text(text);

  return parts
    .map((part, index) => {
      if (index % 2 === 0) return format_inline_text(part);

      const explicit = part.startsWith('\\(');
      const source =
        part.startsWith('$$') || explicit ? part.slice(2, -2) : part.slice(1, -1);

      if (!is_inline_math_source(source, explicit)) return format_inline_text(part);

      return `<span class="math-inline" role="math">${render_math_html(source)}</span>`;
    })
    .join('');
}


/** Inline math must not look like currency or an accidental span. */
function is_inline_math_source(source, explicit = false) {
  if (!source) return false;
  if (!explicit && source !== source.trim()) return false;
  if (!explicit && /^\d/.test(source)) return false;

  return !/(^|[^\\])\$/.test(source);
}


/** Closing delimiter for a multi-line display-math opener, if any. */
function math_block_closer(line) {
  const value = line.trim();

  if (value === '$$') return '$$';
  if (value === '\\[') return '\\]';

  return null;
}


/** Match single-line display math delimited by `$$` or `\\[...\\]`. */
function single_line_display_math(line) {
  return /^\s*\$\$(.+?)\$\$\s*$/.exec(line) || /^\s*\\\[(.+?)\\\]\s*$/.exec(line);
}


/** True when a table header and delimiter pair starts at `index`. */
function is_table_start(lines, index) {
  const header = lines[index];
  const delimiter = lines[index + 1];

  if (!header || !delimiter) return false;
  if (!has_unescaped_pipe(header) || !has_unescaped_pipe(delimiter)) return false;
  if (!is_table_delimiter_row(delimiter)) return false;

  return split_table_row(header).length === split_table_row(delimiter).length;
}


/** True when a row is made only of `:?-+:?` cells. */
function is_table_delimiter_row(line) {
  const cells = split_table_row(line);

  return cells.length > 0 && cells.every((cell) => /^:?-{1,}:?$/.test(cell));
}


/** True when the line contains a pipe that is not backslash-escaped. */
function has_unescaped_pipe(line) {
  let backslashes = 0;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];

    if (char === '|' && backslashes % 2 === 0) return true;

    backslashes = char === '\\' ? backslashes + 1 : 0;
  }

  return false;
}


/** Split a table row on unescaped pipes and drop optional boundary pipes. */
function split_table_row(line) {
  const text = String(line).trim();
  const cells = [];
  let current = '';
  let index = 0;

  while (index < text.length) {
    const char = text[index];

    if (char === '\\' && text[index + 1] === '|') {
      current += '|';
      index += 2;
      continue;
    }

    if (char === '|') {
      cells.push(current);
      current = '';
      index += 1;
      continue;
    }

    current += char;
    index += 1;
  }

  cells.push(current);

  if (text.startsWith('|')) cells.shift();
  if (ends_with_unescaped_pipe(text) && cells.length) cells.pop();

  return cells.map((cell) => cell.trim());
}


/** True when the trimmed row ends with an unescaped pipe. */
function ends_with_unescaped_pipe(text) {
  if (!text.endsWith('|')) return false;

  let backslashes = 0;
  let index = text.length - 2;

  while (index >= 0 && text[index] === '\\') {
    backslashes += 1;
    index -= 1;
  }

  return backslashes % 2 === 0;
}


/** Map a delimiter cell to its alignment keyword. */
function parse_table_alignment(cell) {
  const starts = cell.startsWith(':');
  const ends = cell.endsWith(':');

  if (starts && ends) return 'center';
  if (ends) return 'right';
  if (starts) return 'left';

  return '';
}


/** Pad or truncate a body row so every table row matches the header width. */
function normalize_table_row(cells, column_count) {
  const normalized = [];

  for (let index = 0; index < column_count; index += 1) {
    normalized.push(cells[index] === undefined ? '' : cells[index]);
  }

  return normalized;
}


/** Render an aligned GFM table wrapper with escaped inline cell content. */
function render_table_html(header_cells, alignments, body_rows) {
  const head = header_cells
    .map((cell, index) => `<th${alignment_attribute(alignments[index])}>${inline_to_html(cell)}</th>`)
    .join('');

  const body = body_rows
    .map((row) => {
      const cells = row
        .map((cell, index) => `<td${alignment_attribute(alignments[index])}>${inline_to_html(cell)}</td>`)
        .join('');

      return `<tr>${cells}</tr>`;
    })
    .join('');

  return `<div class="md-table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}


function alignment_attribute(alignment) {
  return alignment ? ` align="${alignment}"` : '';
}
