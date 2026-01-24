
# text-forge

Набор скриптов для преобразования текстов формата Markdown в интерактивный сайт с поиском и возможностью делиться ссылками на отдельные части.
Скрипты также создают электронную книгу и подготовливают форматы для последующего использования ИИ помощниками. 

- Объединённые главы в один текстовый файл: `build/text_combined.txt`
- Нормализованный Markdown в формате Pandoc: `build/pandoc.md`
- Электронная книга в формате EPUB: `build/text_book.epub`
- Сборка сайта MkDocs: `public/ru/`

Скрипты изначально были частью Текста [`bongiozzo/whattodo`](https://github.com/bongiozzo/whattodo), но впоследствии были отделены для переиспользования.

Если Вы связаны с разработкой, то вряд ли потребуется более подробное описание, чем – создайте собственную ветку (Fork) этого репозитария и включите в настройках GitHub запуск действий для публикации (Actions).

Пример скрипта публикации: `examples/content-repo-publish.yml`.
Рабочий скрипт действующего сайта text.sharedgoals.ru, который можно не менять: [`publish.yml`](https://github.com/bongiozzo/whattodo/blob/master/.github/workflows/publish.yml).

Для людей далёких от программной разработки [инструкция с иллюстрациями приведена на примере ответвления от существующего Текста](https://github.com/bongiozzo/whattodo).

Ниже дана краткая выжимка.

## Публикация

Чтобы создать репозиторий с Вашим Текстом на GitHub Pages, достаточно взять в качестве примера имеющийся:

```bash
git clone https://github.com/bongiozzo/whattodo.git
cd whattodo
```

1) Отредактировать файлы в `text/ru/`.

- Можно редактировать или удалить все главы, но важно сохранить `text/ru/index.md` и структуру папок (порядок глав задаётся в `mkdocs.yml`).
- Стили оформления: `text/ru/assets/css/extra.css` (подключается через `mkdocs.yml` → `extra_css`).
- Остальные файлы в `text/ru/assets/` можно удалять или оставить для примера.
- Изображения лежат в `text/ru/img/` — можно удалить/заменить на свои и использовать в тексте.

2) Запустить команду git commit.
3) И следом – git push.

```bash
git commit -a -m "Мой Текст: первые правки"
git push
```

После `push` GitHub Actions сам соберёт сайт и EPUB.

### Обложка EPUB

- Обложка необязательна.
- Если передать `cover_image` и cover.jpg существует, action использует его.
- Если файла нет, EPUB собирается **без** обложки и выведет предупреждение.

### Через VS Code

Откройте вкладку **Source Control** → выберите файлы → напишите сообщение → **Commit** → **Sync/Push**.

## Локальная сборка (для проверки перед публикацией)

Локальная сборка нужна, если хотите проверить сайт/EPUB перед публикацией.
Это требует чуть больше настроек, чем публикация.

### Подготовка

- `uv`: macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh` (или `brew install uv`); Windows (PowerShell): `powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://astral.sh/uv/install.ps1 | iex"` (или `winget install -e --id Astral.uv`)
- `pandoc` (нужен только для EPUB): macOS: `brew install pandoc`; Windows: `winget install -e --id JohnMacFarlane.Pandoc` (или `choco install pandoc`)

```bash
make install
```

### Команды

```bash
make serve          # быстрый локальный предпросмотр (без EPUB и без pandoc)

make                # EPUB + сайт (как в CI)
make epub           # только EPUB
make site           # собрать сайт (EPUB будет построен автоматически)
```

`make serve` не строит EPUB и не требует `pandoc`; он также отключает `git-committers` плагин через `MKDOCS_GIT_COMMITTERS_ENABLED=false`, чтобы упростить локальный вывод.
Если submodule не инициализирован, команды сборки не найдут tooling (`text-forge`).

