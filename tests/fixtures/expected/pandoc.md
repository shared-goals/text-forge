# Introduction

## Test Fixtures {#index-md}

This is a minimal test project for validating the text-forge pipeline.

Internal link test: [Chapter 1](#chapter1-md)

::: chapter-dates
Создано: 2024-01-15 Опубликовано: 2024-01-20 Обновлено: 2025-01-28
:::

# Content

## Chapter 1: Blocks and Links {#chapter1}

### PyMdown Situation Block

::: situation
This is a test situation block that should be converted to a Pandoc div
with a caption.

It has multiple paragraphs.
:::

### Internal Link Test

See also [Chapter 2](#quotes).

::: chapter-dates
Создано: 2024-02-01 Опубликовано: 2024-02-05
:::

## Chapter 2: Quotes and Images {#chapter2}

### Quote Block {#quotes}

::: quote
This is a wise saying that should be preserved correctly.

It spans multiple lines.

[Author Name](https://example.com/author){.author}
:::

### Image with Attributes

![Test Image](img/test.jpg "Test image caption"){width="75%"
loading="lazy"}

Back to [home](#index-md).

::: chapter-dates
Создано: 2024-03-01
:::
