module.exports = async function (tp) {
  
  const blockTypes = [
    { label: 'quote — цитата с автором',             type: 'quote'     },
    { label: 'situation — ситуация из жизни',        type: 'situation' },
    { label: 'note — дополнение / вставка',          type: 'note'      },
    { label: 'abstract — пример / анекдот / притча', type: 'abstract'  },
    { label: 'define — термин и определение',        type: 'define'    },
    { label: 'rule — правило / принцип',             type: 'rule'      },
    { label: 'music — музыкальная вставка',          type: 'music'     },
    { label: 'details — сворачиваемый блок',        type: 'details'   },
  ];  
  
  const choice = await tp.system.suggester(
    blockTypes.map(b => b.label),
    blockTypes
  );  
  
  const selection = tp.file.selection();
  const text = selection && selection.trim() ? selection.trim() : 'Текст';

  if (!choice) return '';
  switch (choice.type) {
    
    case 'quote': {
      // где взять цитату: корпус прочитанных книг или свободный ввод
      const origin = await tp.system.suggester(
        ['Из книги (корпус)', 'Свободная цитата'],
        ['corpus', 'free']
      );
      if (!origin) return '';

      if (origin === 'corpus') {
        const quote = await _corpusQuote(tp);
        if (!quote) return '';
        return `/// quote\n\n${quote.text}\n\n${quote.signature}\n\n///`;
      }

      const quoteText = await tp.system.prompt('Текст цитаты', text);
      if (!quoteText) return '';
      const author = await tp.system.prompt('Автор', 'Автор цитаты');
      const source = await tp.system.prompt('URL источника (необязательно)', 'https://');
      const authorLine = author && source  ? `[${author}](${source}){ .author }`
                       : author            ? `${author}{ .author }`
                       : '';
      return authorLine
        ? `/// quote\n\n${quoteText}\n\n${authorLine}\n\n///`
        : `/// quote\n\n${quoteText}\n\n///`;
    }
  
    case 'situation': {
      return `/// situation\n\n${text}\n\n///`;
    }

    case 'note': {
      return `/// note\n\n${text}\n\n///`;
    }

    case 'abstract': {
      const title = await tp.system.prompt('Заголовок');
      if (!title) return '';
      return `/// abstract | ${title}\n\n${text}\n\n///`;
    }  

    case 'define': {
      const term = await tp.system.prompt('Термин', 'Термин');
      if (!term) return '';
      const definition = await tp.system.prompt('Определение', 'Определение');
      if (!definition) return '';
      return `/// define\n\n${term}\n\n- ${definition}\n\n///`;
    }  

    case 'rule': {
      return `/// rule\n\n${text}\n\n///`;
    }

    case 'music': {
      return `/// music\n\n${text}\n\n///`;
    }

    case 'details': {
      return `/// details\n\n\`\`\`\n${text}\n\`\`\`\n\n///`;
    }

    default:
      return '';
  }
};

// цитата из корпуса: выбрать книгу (title — author из frontmatter),
// затем цитату (блоки `> … ^quote_N`) — текст берётся из корпуса как есть,
// подпись ведёт на локальный анкор books/<slug>.md#quote_N
async function _corpusQuote(tp) {
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
  if (!book) return null;

  const quote = await tp.system.suggester(
    book.quotes.map((q) => `#${q.n} · ${q.preview}`),
    book.quotes
  );
  if (!quote) return null;

  const name = book.author || book.title;
  return {
    text: quote.text,
    signature: `[${name}](${book.link}#${quote.id}){ .author }`,
  };
}

function _frontmatter(content, key) {
  const m = content.match(new RegExp('^' + key + ': (.+)$', 'm'));
  if (!m) return '';
  return m[1].trim().replace(/^"(.*)"$/, '$1');
}

// группы блокцитат `> …`, чья последняя строка кончается блок-id `^quote_N`;
// id становится анкором ссылки — в вставляемый текст он НЕ попадает
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
