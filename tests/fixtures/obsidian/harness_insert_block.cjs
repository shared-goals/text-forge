/**
 * harness_insert_block.cjs — node harness for the quote picker in
 * text_forge/obsidian/scripts/insert_block.js.
 *
 * insert_block.js is a Templater script (`module.exports = async function (tp)`)
 * and cannot be required and called: the quote picker waits on
 * `tp.system.suggester` for user input and reads the vault through the global
 * Obsidian `app`. So the harness reads the file as TEXT, slices the picker's
 * functions out by name, and compiles them with `app` injected as a parameter
 * whose value the harness controls per scenario.
 *
 * Run: node tests/fixtures/obsidian/harness_insert_block.cjs
 * Debug the extracted source: HARNESS_DEBUG=1 node …
 */

const fs = require('fs');
const path = require('path');

const HERE = __dirname;
const SCRIPT = path.resolve(HERE, '../../../text_forge/obsidian/scripts/insert_block.js');
const BOOK_PAGE = 'abe-chetvertyy-lednikovyy-period.md';
// param is `page`, not `content`: `content` is a live global in browsers and in
// node --experimental-eval-side-effects, and shadowing it is cheaper than risking it
const DEFAULT_PAGES = {
  [BOOK_PAGE]: fs.readFileSync(path.join(HERE, BOOK_PAGE), 'utf8'),
};

// ---------------------------------------------------------------------------
// loading the picker out of a Templater script
// ---------------------------------------------------------------------------

/**
 * Slice a `function name(...) { … }` / `async function …` block out of the
 * source. Naive brace counting breaks inside string literals — the picker builds
 * markdown with `${title} — ${author}` — so string/template/regex state is
 * tracked while walking. The scanner is deliberately the simplest thing that
 * survives this file: quotes, escapes, `${}` nesting, regex literals holding
 * braces (`/^#{1,6}\s+…/`) and `[…]` classes, and `//` comments.
 */
function sliceFunction(src, name) {
  const start = src.search(
    new RegExp('^[ \\t]*(?:async[ \\t]+)?function[ \\t]+' + name + '[ \\t]*\\(', 'm')
  );
  if (start < 0) throw new Error('insert_block.js has no ' + name + '()');
  const end = scanToFunctionEnd(src, src.indexOf('{', start));
  if (end < 0) throw new Error('insert_block.js: unbalanced braces reading ' + name + '()');
  return src.slice(start, end);
}

/** Index just past the `}` closing the block whose `{` sits at `open`. */
function scanToFunctionEnd(src, open) {
  let depth = 0;
  let i = open;
  while (i < src.length) {
    const c = src[i];
    const next = src[i + 1];
    if (c === '/' && next === '/') {            // line comment: skip to end of line
      const nl = src.indexOf('\n', i);
      if (nl < 0) return -1;
      i = nl;
      continue;
    }
    if (c === '/' && next === '*') {           // block comment: skip to `*/`
      const close = src.indexOf('*/', i);
      if (close < 0) return -1;
      i = close + 2;
      continue;
    }
    if (c === '\\') { i += 2; continue; }      // escape outside a literal
    if (c === "'" || c === '"') { i = skipLiteral(src, i, c); continue; }
    if (c === '`') { i = skipTemplate(src, i); continue; }
    if (c === '/') { i = skipRegexLiteral(src, i); continue; }
    if (c === '{') depth++;
    else if (c === '}') {
      depth--;
      if (depth === 0) return i + 1;
    }
    i++;
  }
  return -1;
}

/** Skip a `'…'` / `"…"` string starting at `i`; returns the index after it. */
function skipLiteral(src, i, quote) {
  for (let j = i + 1; j < src.length; j++) {
    if (src[j] === '\\') { j++; continue; }
    if (src[j] === '\n') throw new Error('unterminated string literal at ' + i);
    if (src[j] === quote) return j + 1;
  }
  throw new Error('unterminated string literal at ' + i);
}

/** Skip a template literal, including `${ … }` expressions (which may nest). */
function skipTemplate(src, i) {
  for (let j = i + 1; j < src.length; j++) {
    const c = src[j];
    if (c === '\\') { j++; continue; }
    if (c === '`') return j + 1;
    if (c === '$' && src[j + 1] === '{') {
      const close = scanToFunctionEnd(src, j + 1);
      if (close < 0) throw new Error('unterminated ${ } in template at ' + i);
      j = close - 1;
    }
  }
  throw new Error('unterminated template literal at ' + i);
}

/**
 * Skip a `/regex/flags` starting at `i`. A `/` in this file is always a
 * literal — the picker never divides — so no division-vs-regex disambiguation
 * is needed; `[…]` character classes may hold `/` itself.
 */
function skipRegexLiteral(src, i) {
  let inClass = false;
  for (let j = i + 1; j < src.length; j++) {
    const c = src[j];
    if (c === '\\') { j++; continue; }
    if (c === '[') inClass = true;
    else if (c === ']') inClass = false;
    else if (c === '/' && !inClass) {
      let k = j + 1;
      while (k < src.length && /[a-z]/.test(src[k])) k++;   // flags: gimsuvy
      return k;
    }
  }
  throw new Error('unterminated regex literal at ' + i);
}

/** The picker source: the heading regex plus everything _corpusQuote reaches. */
function loadPicker(src) {
  const names = ['_corpusQuote', '_frontmatter', '_quotes', '_collectHeading',
                 '_legacyQuotes', '_legacyCollect'];
  const constLine = src.split('\n').find((l) => l.startsWith('const QUOTE_HEADING'));
  if (!constLine) throw new Error('insert_block.js has no QUOTE_HEADING const');
  return [constLine].concat(names.map((n) => sliceFunction(src, n))).join('\n\n');
}

// ---------------------------------------------------------------------------
// mocks: tp (Templater) and app (Obsidian vault)
// ---------------------------------------------------------------------------

/**
 * tp mock: `suggester` consumes the scripted choices in call order. Templater
 * returns the ITEM (not the label) of the picked row, so a choice is an index
 * into the parallel values/items arrays — or null for "user cancelled". A
 * choice index the picker never offered, or a suggester call beyond the script,
 * is an assertion failure: the picker walked somewhere unexpected.
 */
function makeTp(choices) {
  const queue = choices.slice();
  return {
    file: { selection: () => '' },
    system: {
      suggester: async (values, items) => {
        if (!queue.length) throw new Error('suggester called more often than scripted');
        const i = queue.shift();
        if (i === null) return null;
        if (typeof i !== 'number' || i < 0 || i >= values.length) {
          throw new Error(`bad scripted choice ${JSON.stringify(i)} for ${JSON.stringify(values)}`);
        }
        return items ? items[i] : values[i];
      },
      prompt: async () => null,
    },
  };
}

/** app mock: the vault serves the given pages, all under text/books/. */
function makeApp(pages) {
  const files = Object.keys(pages).map((p) => ({ path: 'text/books/' + p }));
  return {
    vault: {
      getMarkdownFiles: () => files,
      read: async (f) => {
        const name = f.path.replace(/^text\/books\//, '');
        if (!(name in pages)) throw new Error('page not in the mocked vault: ' + name);
        return pages[name];
      },
    },
  };
}

// ---------------------------------------------------------------------------
// scenarios
// ---------------------------------------------------------------------------

const checks = [];
function check(name, fn) {
  checks.push({ name, fn });
}

/**
 * @returns {any} the picker API: `_corpusQuote(tp)` reads the vault the scenario
 * installed with `withVault()`.
 */
let picker = null;
function withVault(pages) {
  const src = fs.readFileSync(SCRIPT, 'utf8');
  if (process.env.HARNESS_DEBUG) console.error('--- extracted picker source ---\n' + loadPicker(src));
  /* eslint-disable-next-line no-new-func -- the whole point of the harness */
  picker = new Function('app', loadPicker(src) + '\nreturn { _corpusQuote, _frontmatter, _quotes };')(
    makeApp(pages)
  );
}

check('1. header-id parsing: ids from headings, text from the block below', () => {
  const quotes = picker._quotes(DEFAULT_PAGES[BOOK_PAGE]);
  assertDeep(quotes.map((q) => q.id), ['quote_1', 'quote_2'], 'quote ids come from the headings');
  assert(quotes[0].n === '1' && quotes[1].n === '2', 'numbering follows the headings');
  assert(quotes[0].text.startsWith('Это было страшное возбуждение'),
         'quote 1 text is the blockquote under its heading');
});

check('2. multi-paragraph quote (bare `>` separator) is ONE quote', () => {
  const quotes = picker._quotes(DEFAULT_PAGES[BOOK_PAGE]);
  assert(quotes[0].text.includes('\n'), 'quote 1 keeps its paragraph break');
  assert(quotes[0].text.includes('Не это ли мы называем ощущением счастья?'),
         'the second paragraph belongs to quote 1, it is not a new quote');
  assert(!quotes[0].text.includes('Сейчас я всего-навсего'), 'quote 2 text stayed out of quote 1');
});

check('3. page without quotes -> empty list', () => {
  const noQuotes = '---\ntitle: "Без цитат"\nauthor: Автор Авторов\n---\n\n'
    + 'Полка: Прочтённые\n\nОбычный текст, блокцитат нет.\n';
  assertDeep(picker._quotes(noQuotes), [], 'no headings, no blockquotes');
  const headingWithoutBody = '---\ntitle: "Заголовок без тела"\n---\n\n## Цитаты\n\n'
    + '### Цитата 1 ^quote_1\n\n— [LiveLib](https://www.livelib.ru/quote/1)\n';
  assertDeep(picker._quotes(headingWithoutBody), [], 'a heading with no blockquote below yields nothing');
});

check('4. the block id never leaks into the inserted text', () => {
  withVault(DEFAULT_PAGES);
  for (const q of picker._quotes(DEFAULT_PAGES[BOOK_PAGE])) {
    assert(!q.text.includes('^'), 'quote text carries no caret: ' + q.text);
    assert(!q.preview.includes('^'), 'preview carries no caret: ' + q.preview);
  }
  return picker._corpusQuote(makeTp([0, 0])).then((out) => {
    assert(!out.text.includes('^'), 'inserted quote text is id-free: ' + out.text);
    assert(!out.signature.includes('^'), 'signature is a link, not a block id: ' + out.signature);
  });
});

check('5. signature keeps books/<slug>.md#quote_N and the author name', async () => {
  withVault(DEFAULT_PAGES);
  const out = await picker._corpusQuote(makeTp([0, 1]));
  assertEqual(out.signature,
              '[Кобо Абэ](books/abe-chetvertyy-lednikovyy-period.md#quote_2){ .author }',
              'signature of quote 2');
});

check('6. authorless book signs with the title', async () => {
  withVault({
    'bez-avtora.md': '---\ntitle: "Книга без автора"\n---\n\n## Цитаты\n\n'
      + '### Цитата 1 ^quote_1\n\n> Фраза.\n\n— [LiveLib](https://www.livelib.ru/quote/9)\n',
  });
  const out = await picker._corpusQuote(makeTp([0, 0]));
  assertEqual(out.signature, '[Книга без автора](books/bez-avtora.md#quote_1){ .author }',
              'the title stands in for a missing author');
});

check('7. legacy page (id on the blockquote line) still parses', () => {
  const legacy = '---\ntitle: "Старая страница"\nauthor: Кобо Абэ\n---\n\n## Цитаты\n\n'
    + '> Первая.\n>\n> Конец. ^quote_1\n\n— [LiveLib](https://www.livelib.ru/quote/1)\n';
  const quotes = picker._quotes(legacy);
  assertDeep(quotes.map((q) => q.id), ['quote_1'], 'legacy ids are still collected');
  assert(!quotes[0].text.includes('^'), 'legacy text is id-free too');
});

// ---------------------------------------------------------------------------
// assertions + runner
// ---------------------------------------------------------------------------

function assert(cond, what) {
  if (!cond) throw new Error('assertion failed: ' + what);
}

function assertEqual(got, want, what) {
  if (got !== want) throw new Error(`${what}\n  got:  ${got}\n  want: ${want}`);
}

function assertDeep(got, want, what) {
  if (JSON.stringify(got) !== JSON.stringify(want)) {
    throw new Error(`${what}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`);
  }
}

withVault(DEFAULT_PAGES); // default vault, available to every scenario

(async () => {
  let failed = 0;
  for (const c of checks) {
    try {
      await c.fn();
      console.log('ok   ' + c.name);
    } catch (e) {
      failed++;
      console.log('FAIL ' + c.name + '\n     ' + e.message.split('\n').join('\n     '));
    }
  }
  console.log(failed ? `\n${failed} of ${checks.length} scenarios failed`
                     : `\nall ${checks.length} scenarios passed`);
  process.exit(failed ? 1 : 0);
})();
