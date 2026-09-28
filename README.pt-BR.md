[English](README.md) · **Português (Brasil)**

# sitemap-lastmod-audit

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) ![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)

`sitemap-lastmod-audit` é uma ferramenta gratuita, de código aberto e de
linha de comando, que confere se as datas `<lastmod>` de um sitemap contam
a verdade sobre as páginas, e se as URLs listadas deveriam mesmo estar no
sitemap. Ela lê o sitemap (inclusive index, `.xml.gz` e `robots.txt`),
audita cada `<lastmod>` e, com `--verify`, baixa uma amostra de páginas e
compara a data do sitemap com as datas que cada página declara.

## Sumário

- [Contexto](#contexto)
- [O que a ferramenta verifica](#o-que-a-ferramenta-verifica)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Uso](#uso)
- [Perguntas frequentes](#perguntas-frequentes)
- [Limitações](#limitações)
- [Método e origem](#método-e-origem)
- [Como contribuir](#como-contribuir)
- [Autor](#autor)
- [Licença](#licença)

## Contexto

A documentação do Google sobre como montar sitemaps (Google Search
Central, página atualizada em 2026) diz que o Google usa o `<lastmod>`
quando ele é preciso de forma consistente e verificável, por exemplo
quando bate com a última modificação da página, e que ignora
`<changefreq>` e `<priority>`:
[Build and submit a sitemap](https://developers.google.com/search/docs/crawling-indexing/sitemaps/build-sitemap).
Em junho de 2023, o post
[Sitemaps ping endpoint is going away](https://developers.google.com/search/blog/2023/06/sitemaps-lastmod-ping)
acrescentou que o `lastmod` é usado como sinal para agendar o rastreamento
de URLs já descobertas, que ele precisa estar em um formato de data
suportado e que deve refletir a última mudança significativa da página,
não uma mudança na barra lateral ou no rodapé.

Gerador de sitemap que carimba a data do build em todas as URLs quebra
exatamente essa consistência. `sitemap-lastmod-audit` encontra esses
padrões e, em uma amostra, compara o sitemap com a própria página.

## O que a ferramenta verifica

No arquivo do sitemap, para cada URL:

1. **`<lastmod>` ausente.**
2. **Formato inválido.** Qualquer coisa fora dos formatos W3C Datetime
   (`2026`, `2026-09`, `2026-09-28`, ou data e hora com fuso, como
   `2026-09-28T10:00:00+00:00`).
3. **Data no futuro.**
4. **Muitas URLs com o mesmo `<lastmod>`.** Quando o valor mais comum
   cobre `--same-ratio` das URLs ou mais (padrão 0.5), o relatório mostra a
   data e a porcentagem, no sitemap inteiro e em cada sitemap filho. É
   sinal de lastmod gerado no build.
5. **Tudo igual ao sitemap index.** Todas as URLs de um sitemap filho com o
   mesmo `<lastmod>` que o index declara para aquele filho.
6. **URL listada mais de uma vez.**

Com `--verify`, em uma amostra aleatória (`--sample`, padrão 20, `--seed`
para repetir a mesma amostra) e com crawl educado:

7. **Divergência de data.** Compara o `<lastmod>` com o `dateModified` do
   nó principal do JSON-LD e com a meta `article:modified_time` ou
   `og:updated_time`, e aponta diferença maior que `--tolerance-days`
   (padrão 2). O header `Last-Modified` só conta quando a página não tem
   data própria, porque em CMS com cache ele costuma refletir a hora do
   cache; nos outros casos, sai como informação.
8. **URL que não deveria estar no sitemap.** Status diferente de 200,
   redirecionamento, canonical apontando para outra URL ou `noindex` (meta
   robots ou `X-Robots-Tag`).

Os padrões de proporção e de tolerância são pontos de partida ajustáveis.
O Google não publica percentual de lastmod repetido nem tolerância em
dias.

## Requisitos

Python 3.9 ou mais recente e `requests` (veja `requirements.txt`). O HTML
é lido com o parser da biblioteca padrão.

## Instalação

```bash
git clone https://github.com/LucasFerrazSEO/sitemap-lastmod-audit.git
cd sitemap-lastmod-audit
pip install -r requirements.txt
```

## Uso

**1. Audite o arquivo.** Sem `--verify`, só o sitemap é lido.

```bash
python sitemap_lastmod_audit.py --file examples/sitemap-exemplo.xml
```

Saída real com o exemplo fictício (example.com) da pasta `examples/`:

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

**2. Compare com as páginas ao vivo.** Uma execução real contra o
lucasferrazseo.com:

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

As páginas da amostra estavam coerentes com o próprio `dateModified`; o
header `Last-Modified` refletia a hora do cache, e por isso aparece só
como informação. E uma execução contra o lucasferraz.com, encurtada:

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

Aqui a data repetida é um dia real de publicação de um lote de posts, e o
alerta serve de convite para conferir, não de prova de problema. A
amostra também mostra que a maioria das páginas não declara data de
modificação que a ferramenta consiga comparar.

**3. Salve uma linha por URL.** O CSV traz URL, sitemap, lastmod, o
lastmod do index, status, destino do redirecionamento, canonical,
noindex, as três datas da página, a maior divergência e os problemas
encontrados.

```bash
python sitemap_lastmod_audit.py https://example.com/sitemap.xml --verify --csv lastmod.csv
```

**4. Use em CI/CD.**

```bash
python sitemap_lastmod_audit.py https://example.com/sitemap.xml --strict   # código de saída 1 se houver ATENÇÃO ou FAIL
```

## Perguntas frequentes

**O Google exige `<lastmod>`?**
Não. A documentação do Google trata o campo como opcional e diz que ele é
usado quando é preciso de forma consistente. O post de junho de 2023 diz
também que não tem problema deixar o campo de fora nas páginas em que o
software não consegue saber a data real de modificação.

**É errado muitas URLs terem a mesma data?**
Nem sempre. Um lote publicado no mesmo dia vai dividir a data. O alerta
existe porque sitemap em que quase toda URL carrega a data do build é o
jeito mais comum de o lastmod deixar de bater com a realidade. Confira
algumas das páginas listadas antes de mudar qualquer coisa.

**Por que o header `Last-Modified` não conta como divergência?**
Em páginas de CMS atrás de cache, esse header costuma informar quando o
cache foi gerado. Quando a página declara data própria (JSON-LD ou meta),
essa data vale. O header só conta quando é a única data disponível.

**Corrigir o lastmod faz o Google rastrear ou indexar mais rápido?**
A ferramenta não promete isso. Ela confere se o sitemap é coerente com as
páginas; como e quando um buscador rastreia é decisão dele.

## Limitações

A ferramenta não executa JavaScript, então data injetada na página depois
do carregamento não é vista. Ela compara o que o sitemap declara com o que
a página declara; não tem como saber quando o texto mudou de fato.
`<lastmod>` só com data é comparado no nível do dia. A amostra é
aleatória: rode mais de uma vez, ou aumente `--sample`, antes de tirar
conclusão sobre um sitemap grande.

## Método e origem

A ferramenta generaliza uma lição interna do
[lucasferrazseo.com](https://lucasferrazseo.com): antes de pedir a
reindexação de uma página, confirmar que o sitemap traz um lastmod real, e
não a data do último build. A versão pública não tem nenhuma regra
específica de site, e todo limiar é parâmetro.

## Como contribuir

Relatos de erro e sugestões são bem-vindos pelas [Issues do GitHub](https://github.com/LucasFerrazSEO/sitemap-lastmod-audit/issues).

## Autor

[Lucas Ferraz](https://lucasferraz.com) é especialista em SEO, criação de sites e Generative Engine Optimization e fundador da [Lucas Ferraz SEO](https://lucasferrazseo.com).

## Licença

MIT. Veja o arquivo [LICENSE](LICENSE).
