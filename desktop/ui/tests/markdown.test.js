import assert from 'node:assert/strict';
import test from 'node:test';

import { escape_html, markdown_to_html } from '../src/core/markdown.js';


test('renders a GFM table with alignment and inline formatting', () => {
  const html = markdown_to_html([
    '| Name | Qty | Note |',
    '| :--- | ---: | :---: |',
    '| **alpha** | `7` | plain |',
  ].join('\n'));

  assert.match(html, /<div class="md-table-wrap">/);
  assert.match(
    html,
    /<thead><tr><th align="left">Name<\/th><th align="right">Qty<\/th><th align="center">Note<\/th><\/tr><\/thead>/,
  );
  assert.match(html, /<td align="left"><strong>alpha<\/strong><\/td>/);
  assert.match(html, /<td align="right"><code>7<\/code><\/td>/);
  assert.match(html, /<tbody><tr>/);
});


test('unescapes escaped pipes inside table cells', () => {
  const html = markdown_to_html('| A | B |\n| --- | --- |\n| x \\| y | `a\\|b` |');

  assert.match(html, /<td>x \| y<\/td>/);
  assert.match(html, /<td><code>a\|b<\/code><\/td>/);
});


test('accepts rows without leading or trailing pipes', () => {
  const html = markdown_to_html('a | b\n--- | ---\n1 | 2');

  assert.match(html, /<th>a<\/th>/);
  assert.match(html, /<td>2<\/td>/);
});


test('pads and truncates ragged table rows', () => {
  const html = markdown_to_html('| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |\n| 1 | 2 | 3 | 4 |');
  const body = /<tbody>(.*)<\/tbody>/.exec(html)[1];

  assert.equal((body.match(/<tr>/g) || []).length, 2);
  assert.equal((body.match(/<td/g) || []).length, 6);
  assert.match(html, /<td>1<\/td><td>2<\/td><td><\/td>/);
  assert.doesNotMatch(html, /<td>4<\/td>/);
});


test('falls back to paragraph text when no delimiter row follows', () => {
  const html = markdown_to_html('| a | b |\n| c | d |');

  assert.doesNotMatch(html, /<table/);
  assert.match(html, /\| a \| b \|/);
  assert.match(html, /\| c \| d \|/);
});


test('falls back when the delimiter column count mismatches', () => {
  const html = markdown_to_html('| a | b |\n| --- |');

  assert.doesNotMatch(html, /<table/);
  assert.match(html, /\| a \| b \|/);
});


test('terminates a preceding paragraph at a table header', () => {
  const html = markdown_to_html('intro text\n| a | b |\n| --- | --- |\n| 1 | 2 |');

  assert.match(html, /^<p>intro text<\/p>/);
  assert.match(html, /<table>/);
});


test('does not parse tables inside fenced code', () => {
  const html = markdown_to_html('```\n| a | b |\n| --- | --- |\n```');

  assert.match(html, /<pre><code>/);
  assert.doesNotMatch(html, /md-table-wrap/);
});


test('renders multi-line display math', () => {
  const html = markdown_to_html(String.raw`$$
\frac{a}{b} = \sqrt{x^2} + \alpha
$$`);

  assert.match(html, /<div class="math-block" role="math">/);
  assert.match(html, /class="katex-display"/);
  assert.match(html, /mfrac/);
  assert.match(html, /msqrt/);
  assert.match(html, /\u03b1/);
  assert.match(html, /msup/);
  assert.doesNotMatch(html, /<p>/);
});


test('renders single-line display math', () => {
  const html = markdown_to_html('$$E = mc^2$$');

  assert.match(html, /<div class="math-block" role="math">/);
  assert.match(html, /class="katex-display"/);
  assert.match(html, /<msup><mi>c<\/mi><mn>2<\/mn><\/msup>/);
});


test('renders display math with LaTeX bracket delimiters', () => {
  const html = markdown_to_html(String.raw`\[
PE_{(pos,\,2i)} = \sin\!\left(\frac{pos}{10000^{2i/d}}\right)
\]`);

  assert.match(html, /<div class="math-block" role="math">/);
  assert.match(html, /class="katex-display"/);
  assert.match(html, /mfrac/);
  assert.doesNotMatch(html, /<p>/);
});


test('renders single-line bracket display math', () => {
  const html = markdown_to_html(String.raw`\[E = mc^2\]`);

  assert.match(html, /<div class="math-block" role="math">/);
  assert.match(html, /class="katex-display"/);
  assert.match(html, /<msup><mi>c<\/mi><mn>2<\/mn><\/msup>/);
});


test('renders inline math with LaTeX paren delimiters', () => {
  const html = markdown_to_html(String.raw`value \(x^2\) here`);

  assert.match(html, /class="math-inline"/);
  assert.match(html, /<msup><mi>x<\/mi><mn>2<\/mn><\/msup>/);
});


test('marks unclosed bracket display math as pending', () => {
  const html = markdown_to_html(String.raw`before
\[
x + 1`);

  assert.match(html, /^<p>before<\/p>/);
  assert.match(html, /math-block math-block-pending/);
  assert.match(html, /<mi>x<\/mi>/);
});


test('renders sums, integrals, and text commands', () => {
  const html = markdown_to_html(String.raw`$$\sum_{i=1}^{n} \int_0^1 \text{rate}\, dx$$`);

  assert.match(html, /\u2211/);
  assert.match(html, /munderover/);
  assert.match(html, /<msubsup><mo>\u222b<\/mo>/);
  assert.match(html, /<mtext>rate<\/mtext>/);
});


test('escapes HTML inside math', () => {
  const html = markdown_to_html('$$\n<script>alert(1)</script>\n$$');

  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /script/);
  assert.match(html, /alert\(1\)/);
});


test('marks unclosed display math as pending without losing text', () => {
  const pending = markdown_to_html('before\n$$\nx + 1');

  assert.match(pending, /^<p>before<\/p>/);
  assert.match(pending, /math-block math-block-pending/);
  assert.match(pending, /<mi>x<\/mi>/);
  assert.match(pending, /<mn>1<\/mn>/);

  const closed = markdown_to_html('before\n$$\nx + 1\n$$');

  assert.doesNotMatch(closed, /math-block-pending/);
  assert.match(closed, /<div class="math-block" role="math">/);
});


test('does not treat currency as math', () => {
  const html = markdown_to_html('cost is $5 and $10 total');

  assert.doesNotMatch(html, /math-block/);
  assert.doesNotMatch(html, /math-inline/);
  assert.match(html, /\$5/);
});


test('renders safe inline math', () => {
  const html = markdown_to_html('value $x^2$ here');

  assert.match(html, /class="math-inline"/);
  assert.match(html, /<msup><mi>x<\/mi><mn>2<\/mn><\/msup>/);
});


test('rejects inline math that looks like a currency amount', () => {
  const html = markdown_to_html('pay $5 today');

  assert.doesNotMatch(html, /math-inline/);
  assert.match(html, /\$5/);
});


test('preserves existing heading, list, blockquote, code, hr, and link behavior', () => {
  assert.equal(markdown_to_html('# Title'), '<h1>Title</h1>');
  assert.equal(markdown_to_html('- a\n- b'), '<ul><li>a</li><li>b</li></ul>');
  assert.equal(markdown_to_html('1. a\n2. b'), '<ol><li>a</li><li>b</li></ol>');
  assert.equal(markdown_to_html('> quote'), '<blockquote>quote</blockquote>');
  assert.equal(markdown_to_html('a\n\n---\n\nb'), '<p>a</p><hr><p>b</p>');
  assert.match(markdown_to_html('```js\nconst a = 1;\n```'), /code-lang">js</);
  assert.match(markdown_to_html('[x](https://example.com)'), /href="https:\/\/example.com"/);
  assert.match(markdown_to_html('**bold** and *em*'), /<strong>bold<\/strong>/);
});


test('escapes raw HTML before formatting', () => {
  assert.equal(escape_html('<b>&"'), '&lt;b&gt;&amp;&quot;');
  assert.match(markdown_to_html('<script>alert(1)</script>'), /&lt;script&gt;/);
});