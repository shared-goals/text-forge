module.exports = async function (tp) {

  // one pass over the book corpus: frontmatter (title/author) + quote anchors
  const files = app.vault
    .getMarkdownFiles()
    .filter((f) => f.path.startsWith('text/books/'));

  const books = [];
  for (const f of files) {
    const content = await app.vault.read(f);
    const title = _frontmatter(content, 'title');
    const quotes = _quotes(content);
    if (!title || !quotes.length) continue;
    const author = _frontmatter(content, 'author');
    books.push({
      display: author ? `${title} — ${author}` : title,
      // the page target as seen from a chapter at text/: books/<slug>.md
      link: f.path.replace(/^text\//, ''),
      author: author,
      title: title,
      quotes: quotes,
    });
  }

  const book = await tp.system.suggester(
    books.map((b) => b.display),
    books
  );
  if (!book) return '';

  const quote = await tp.system.suggester(
    book.quotes.map((q) => `#${q.n} · ${q.preview}`),
    book.quotes
  );
  if (!quote) return '';

  const name = book.author || book.title;
  return `/// quote\n\n${quote.text}\n\n[${name}](${book.link}#${quote.id}){ .author }\n\n///`;
};

function _frontmatter(content, key) {
  const m = content.match(new RegExp('^' + key + ': (.+)$', 'm'));
  if (!m) return '';
  return m[1].trim().replace(/^"(.*)"$/, '$1');
}

// blockquote groups `> …` whose last line ends with an Obsidian block id
// `^quote_N`; the id becomes the link anchor, it is NOT inserted with the text
function _quotes(content) {
  const quotes = [];
  let lines = [];
  for (const line of content.split('\n')) {
    if (line.startsWith('> ')) {
      lines.push(line.slice(2));
    } else if (lines.length) {
      _collect(lines, quotes);
      lines = [];
    }
  }
  _collect(lines, quotes);
  return quotes;
}

function _collect(lines, quotes) {
  const text = lines.join('\n').trim();
  const m = text.match(/ \^(quote_\d+)$/);
  if (!m) return;
  const body = text.slice(0, -m[0].length).trim();
  const preview = body.replace(/\n/g, ' ');
  quotes.push({
    id: m[1],
    n: m[1].split('_')[1],
    text: body,
    preview: preview.length > 80 ? preview.slice(0, 80) + '…' : preview,
  });
}
