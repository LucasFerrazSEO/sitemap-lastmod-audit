**English** · [Português (Brasil)](README.pt-BR.md)

# sitemap-lastmod-audit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) ![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)

`sitemap-lastmod-audit` is a free, open source command-line tool that
checks whether the `<lastmod>` dates in a sitemap tell the truth about the
pages, and whether the URLs listed there belong in a sitemap at all. It
reads the sitemap (index, `.xml.gz` or `robots.txt` included), audits every
`<lastmod>` and, with `--verify`, downloads a sample of pages and compares
the sitemap date with the dates each page declares.

The tool prints its report in Brazilian Portuguese.

## Contents

- [Background](#background)
- [What it checks](#what-it-checks)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [FAQ](#faq)
- [Limitations](#limitations)
- [Methodology](#methodology)
- [Contributing](#contributing)
- [Author](#author)
- [License](#license)

## Background

Google's documentation on building sitemaps (Google Search Central, page
updated in 2026) says Google uses `<lastmod>` when it is "consistently and
verifiably" accurate, for example when it matches the last modification of
the page, and that it ignores `<changefreq>` and `<priority>`:
[Build and submit a sitemap](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap).
In June 2023, the post
[Sitemaps ping endpoint is going away](https://developers.google.com/search/blog/2023/06/sitemaps-lastmod-ping)
added that `lastmod` is used as a signal for scheduling crawls of URLs
already discovered, that it must be in a supported date format, and that
it should reflect the last significant change to the page, not a change in
the sidebar or footer.

A sitemap generator that stamps the build date on every URL breaks exactly
that consistency. `sitemap-lastmod-audit` finds those patterns and, on a
sample, compares the sitemap with the page itself.

## What it checks

In the sitemap file, for every URL:

1. **Missing `<lastmod>`.**
2. **Invalid format.** Anything outside the W3C Datetime formats (`2026`,
   `2026-09`, `2026-09-28`, or date and time with a time zone, such as
   `2026-09-28T10:00:00+00:00`).
3. **Date in the future.**
4. **Many URLs with the same `<lastmod>`.** When the most common value
   covers `--same-ratio` of the URLs or more (default 0.5), the report shows
   the date and the percentage, for the whole sitemap and for each child
   sitemap. It is a sign of a lastmod generated at build time.
5. **Every URL equal to the sitemap index.** All URLs of a child sitemap
   with the same `<lastmod>` the index declares for that child.
6. **URL listed more than once.**

With `--verify`, on a random sample (`--sample`, default 20, `--seed` for
repeatability) and with a polite crawl:

7. **Date divergence.** Compares `<lastmod>` with the JSON-LD
   `dateModified` of the main node and with the `article:modified_time` or
   `og:updated_time` meta tag, and flags a difference greater than
   `--tolerance-days` (default 2). The `Last-Modified` header only counts
   when the page has no date of its own, because on cached CMS pages it
   usually reflects the cache time; otherwise it is reported as information.
8. **URLs that should not be in the sitemap.** Status other than 200,
   redirects, a canonical pointing to another URL, or `noindex` (meta
   robots or `X-Robots-Tag`).

The ratio and tolerance defaults are adjustable starting points. Google
does not publish a percentage of repeated lastmod or a tolerance in days.

## Requirements

Python 3.9 or newer and `requests` (see `requirements.txt`). HTML is read
with the standard library parser.

## Installation

```bash
git clone https://github.com/LucasFerrazSEO/sitemap-lastmod-audit.git
cd sitemap-lastmod-audit
pip install -r requirements.txt
```

## Usage

**1. Audit the file.** Without `--verify`, only the sitemap is read.

```bash
python sitemap_lastmod_audit.py --file examples/sitemap-exemplo.xml
```

Real output with the fictitious example (example.com) in `examples/`:

```
=== sitemap-lastmod-audit: examples/sitemap-exemplo.xml ===
10 URL(s) em 1 sitemap(s) | com lastmod: 9 (90%) | URLs repetidas no sitemap: 0
lastmod mais antigo: 2025-11-02 | mais recente: 2031-01-01 | hoje (UTC): 2026-09-28

ATENÇÃO  sitemap inteiro: 5 de 8 URLs (62%) com o mesmo lastmod 2026-09-20T08:00:00Z (sinal de lastmod gerado no build)

FAIL  lastmod fora do formato W3C Datetime: 1
  https://example.com/blog/tinta-lavavel/
      lastmod fora do formato W3C Datetime: '14/03/2026'

FAIL  lastmod no futuro: 1
  https://example.com/blog/rejunte/
      lastmod no futuro: 2031-01-01

ATENÇÃO  sem <lastmod>: 1 URL(s)
  https://example.com/contato/

(Sem --verify: só checagens do arquivo. Use --verify --sample N para comparar com as páginas.)

Resumo: FAIL 2 | ATENÇÃO 6 | URLs sem problema: 2 de 10
```

**2. Compare with the live pages.** A real run against lucasferrazseo.com:

```bash
python sitemap_lastmod_audit.py https://lucasferrazseo.com/sitemap_index.xml --verify --sample 10 --show 5
```

```
=== sitemap-lastmod-audit: https://lucasferrazseo.com/sitemap_index.xml ===
325 URL(s) em 14 sitemap(s) | com lastmod: 324 (100%) | URLs repetidas no sitemap: 1
  ATENÇÃO  URL listada mais de uma vez: https://lucasferrazseo.com/blog/seo-estrategico/posicionamento-no-google/
lastmod mais antigo: 2026-06-21 | mais recente: 2026-09-28 | hoje (UTC): 2026-09-28

ATENÇÃO  https://lucasferrazseo.com/llms-sitemap.xml: 7 de 7 URLs (100%) com o mesmo lastmod 2026-09-28T03:04:15Z (sinal de lastmod gerado no build)
ATENÇÃO  https://lucasferrazseo.com/llms-sitemap.xml: todas as 7 URLs têm o lastmod igual ao do sitemap index (2026-09-28T03:04:15+00:00)

ATENÇÃO  sem <lastmod>: 1 URL(s)
  https://lucasferrazseo.com/locations.kml

Verificação ao vivo: amostra de 10 URL(s), tolerância 2 dia(s)
  200, indexável e com canonical própria: 10 | com data para comparar: 10 | lastmod coerente com a página: 10
  10 URL(s) com header Last-Modified fora da tolerância, mas com data própria coerente na página (header de cache, informativo)

Resumo: FAIL 0 | ATENÇÃO 15 | URLs sem problema: 317 de 325
```

The sample pages were consistent with their own `dateModified`; the
`Last-Modified` header reflected the cache time, which is why it only
shows as information. And a run against lucasferraz.com, shortened:

```
=== sitemap-lastmod-audit: https://lucasferraz.com/sitemap.xml ===
58 URL(s) em 1 sitemap(s) | com lastmod: 58 (100%) | URLs repetidas no sitemap: 0
lastmod mais antigo: 2026-09-22 | mais recente: 2026-09-27 | hoje (UTC): 2026-09-28

ATENÇÃO  sitemap inteiro: 40 de 58 URLs (69%) com o mesmo lastmod 2026-09-23 (sinal de lastmod gerado no build)

Verificação ao vivo: amostra de 10 URL(s), tolerância 2 dia(s)
  200, indexável e com canonical própria: 10 | com data para comparar: 1 | lastmod coerente com a página: 1

  9 URL(s) da amostra sem data nenhuma na página nem no header para comparar:
    https://lucasferraz.com/blog/profundidade-de-clique/
    ...
```

Here the repeated date is a real publishing day for a batch of posts, so
the warning is a prompt to check, not proof of a problem. The sample also
shows that most pages declare no modification date the tool can compare.

**3. Save one row per URL.** The CSV has the URL, sitemap, lastmod, the
index lastmod, status, redirect target, canonical, noindex, the three page
dates, the largest divergence and the problems found.

```bash
python sitemap_lastmod_audit.py https://example.com/sitemap.xml --verify --csv lastmod.csv
```

**4. Use it in CI/CD.**

```bash
python sitemap_lastmod_audit.py https://example.com/sitemap.xml --strict   # código de saída 1 se houver ATENÇÃO ou FAIL
```

## FAQ

**Does Google require `<lastmod>`?**
No. Google's documentation treats it as optional and says it is used when
it is consistently accurate. The June 2023 post also says it is fine to
leave it out on pages where the software cannot tell the real modification
date.

**Is it wrong for many URLs to share the same date?**
Not always. A batch published on the same day will share a date. The
warning exists because a sitemap where almost every URL carries the build
date is the most common way lastmod stops matching reality. Check a few of
the listed pages before changing anything.

**Why does the `Last-Modified` header not count as a divergence?**
On CMS pages behind a cache, that header usually reports when the cache was
generated. When the page declares its own date (JSON-LD or meta tag), that
date wins. The header only counts when it is the only date available.

**Will fixing lastmod make Google crawl or index my pages faster?**
The tool does not promise that. It checks whether the sitemap is
consistent with the pages; how and when a search engine crawls is its own
decision.

## Limitations

The tool does not run JavaScript, so a date injected into the page after
load is not seen. It compares what the sitemap declares with what the page
declares; it cannot know when the text actually changed. A date-only
`<lastmod>` is compared at day level. The sample is random: run it more
than once, or raise `--sample`, before drawing conclusions about a large
sitemap.

## Methodology

The tool generalizes an internal lesson from
[lucasferrazseo.com](https://lucasferrazseo.com): before asking for a page
to be reindexed, confirm that the sitemap carries a real lastmod and not
the date of the last build. The public version has no site-specific rule,
and every threshold is a parameter.

## Contributing

Bug reports and suggestions are welcome through [GitHub Issues](https://github.com/LucasFerrazSEO/sitemap-lastmod-audit/issues).

## Author

[Lucas Ferraz](https://lucasferraz.com) is an SEO, website development and Generative Engine Optimization specialist and the founder of [Lucas Ferraz SEO](https://lucasferrazseo.com).

## License

MIT. See [LICENSE](LICENSE).
