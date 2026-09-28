#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sitemap-lastmod-audit: confere se o <lastmod> de um sitemap conta a verdade
sobre as páginas, e se as URLs listadas são URLs que deveriam estar lá.

O QUE FAZ
    Lê um sitemap (URL, sitemap index, .xml.gz ou robots.txt com linhas
    Sitemap:) ou um arquivo local (--file) e audita cada <lastmod>:

    - ausente;
    - formato inválido (W3C Datetime: AAAA, AAAA-MM, AAAA-MM-DD ou data e
      hora com fuso, como 2026-09-28T10:00:00+00:00);
    - data no futuro;
    - muitas URLs com o MESMO lastmod (sinal de lastmod gerado no build,
      --same-ratio, padrão 0.5): mostra a data e a porcentagem;
    - todas as URLs de um sitemap filho com lastmod idêntico ao que o
      sitemap index declara para aquele filho.

    Com --verify, baixa uma amostra (--sample, padrão 20) com crawl educado
    e compara o lastmod com o header Last-Modified e com as datas da página
    (meta article:modified_time, og:updated_time e dateModified do JSON-LD),
    apontando divergência maior que --tolerance-days (padrão 2). Na mesma
    amostra, lista URL que responde diferente de 200, que redireciona, que
    tem canonical apontando para outra URL ou que tem noindex (meta robots
    ou header X-Robots-Tag).

MÉTODO
    Generalização de uma checagem interna de lucasferrazseo.com: antes de
    pedir reindexação de uma página, conferir se o sitemap declara um
    lastmod real, e não a data do último build. Datas comparadas em UTC;
    data sem hora vale como meia-noite UTC daquele dia. Os limiares são
    pontos de partida ajustáveis, não números publicados pelo Google.

USO
    python sitemap_lastmod_audit.py https://exemplo.com/sitemap.xml
    python sitemap_lastmod_audit.py https://exemplo.com/robots.txt
    python sitemap_lastmod_audit.py --file examples/sitemap-exemplo.xml
    python sitemap_lastmod_audit.py https://exemplo.com/sitemap_index.xml --verify --sample 10
    python sitemap_lastmod_audit.py https://exemplo.com/sitemap.xml --csv lastmod.csv
    python sitemap_lastmod_audit.py https://exemplo.com/sitemap.xml --strict   # saída 1 se houver ATENÇÃO/FAIL

LIMITAÇÕES
    Não executa JavaScript: data injetada no DOM depois do carregamento não
    é vista. O header Last-Modified de páginas geradas por CMS com cache
    costuma refletir a hora do cache, não a da edição; por isso ele aparece
    separado das datas da página. A ferramenta mostra coerência entre o que
    o sitemap declara e o que a página declara; ela não sabe quando o texto
    mudou de fato.

Autor: Lucas Ferraz (lucasferraz.com).
Dependências: requests (ver requirements.txt).
Licença: MIT.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse

try:
    import requests
except ImportError:
    print(
        "Dependência faltando. Instale com:\n"
        "    pip install -r requirements.txt",
        file=sys.stderr,
    )
    sys.exit(2)

NOME = "sitemap-lastmod-audit"
UA = {"User-Agent": f"{NOME}/1.0 (+https://github.com/LucasFerrazSEO/{NOME})"}
TIMEOUT = 30

# W3C Datetime (https://www.w3.org/TR/NOTE-datetime), os seis formatos
RE_W3C = re.compile(
    r"^(\d{4})"
    r"(?:-(\d{2})"
    r"(?:-(\d{2})"
    r"(?:T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:\d{2}))?"
    r")?)?$"
)


def parse_w3c(valor: str) -> datetime | None:
    """Devolve datetime em UTC ou None se o formato não for W3C Datetime."""
    m = RE_W3C.match(valor.strip())
    if not m:
        return None
    ano, mes, dia, hh, mi, ss, frac, tz = m.groups()
    try:
        if hh is None:
            return datetime(int(ano), int(mes or 1), int(dia or 1), tzinfo=timezone.utc)
        dt = datetime(int(ano), int(mes), int(dia), int(hh), int(mi), int(ss or 0),
                      int((frac or "0")[:6].ljust(6, "0")))
        if tz == "Z":
            off = timedelta(0)
        else:
            sinal = 1 if tz[0] == "+" else -1
            off = sinal * timedelta(hours=int(tz[1:3]), minutes=int(tz[4:6]))
        return (dt - off).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def parse_data_livre(valor: str) -> datetime | None:
    """Datas da página (ISO 8601 mais solto que o W3C). None se não der."""
    v = valor.strip()
    dt = parse_w3c(v)
    if dt:
        return dt
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Rede
# ---------------------------------------------------------------------------
class Cliente:
    def __init__(self, delay: float):
        self.s = requests.Session()
        self.s.headers.update(UA)
        self.delay = delay
        self._ultimo = 0.0
        self.erros: list[tuple[str, str]] = []

    def get(self, url: str, redirecionar: bool = True) -> "requests.Response | None":
        for tentativa in (1, 2):
            espera = self.delay - (time.monotonic() - self._ultimo)
            if espera > 0:
                time.sleep(espera)
            try:
                r = self.s.get(url, timeout=TIMEOUT, allow_redirects=redirecionar)
            except requests.RequestException as exc:
                self._ultimo = time.monotonic()
                self.erros.append((url, f"erro de rede: {exc.__class__.__name__}"))
                return None
            self._ultimo = time.monotonic()
            if r.status_code == 429 and tentativa == 1:
                ra = r.headers.get("Retry-After", "")
                pausa = max(5, min(int(ra) if ra.isdigit() else 30, 120))
                print(f"  429 em {url}: esperando {pausa}s e tentando de novo uma vez", file=sys.stderr)
                time.sleep(pausa)
                continue
            if r.status_code == 429:
                self.erros.append((url, "429 (limite de requisições), aumente --delay"))
            return r
        return None


# ---------------------------------------------------------------------------
# Sitemap
# ---------------------------------------------------------------------------
@dataclass
class Entrada:
    loc: str
    lastmod: str | None
    sitemap: str
    lastmod_index: str | None  # o lastmod que o index declara para o sitemap filho
    problemas: list[tuple[str, str]] = field(default_factory=list)  # (nível, texto)
    verificacao: dict = field(default_factory=dict)


def sem_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def filho(el, nome: str) -> str | None:
    for c in el:
        if sem_ns(c.tag) == nome and c.text and c.text.strip():
            return c.text.strip()
    return None


def bytes_xml(dados: bytes) -> bytes:
    return gzip.decompress(dados) if dados[:2] == b"\x1f\x8b" else dados


def le_sitemap(obter, url: str, entradas: list[Entrada], erros: list, visitados: set,
               lastmod_index: str | None = None, limite: int = 500) -> None:
    if url in visitados or len(visitados) >= limite:
        return
    visitados.add(url)
    dados = obter(url)
    if dados is None:
        return
    if url.endswith("robots.txt"):
        for f in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", dados.decode("utf-8", "replace")):
            le_sitemap(obter, f.strip(), entradas, erros, visitados, None, limite)
        return
    try:
        raiz = ET.fromstring(bytes_xml(dados))
    except (ET.ParseError, OSError) as exc:
        erros.append((url, f"XML inválido: {exc}"))
        return
    if sem_ns(raiz.tag) == "sitemapindex":
        for sm in raiz:
            loc = filho(sm, "loc")
            if loc:
                le_sitemap(obter, loc, entradas, erros, visitados, filho(sm, "lastmod"), limite)
    else:
        for u in raiz:
            loc = filho(u, "loc")
            if loc:
                entradas.append(Entrada(loc, filho(u, "lastmod"), url, lastmod_index))


# ---------------------------------------------------------------------------
# Página
# ---------------------------------------------------------------------------
class LeitorHead(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.canonical = ""
        self.robots: list[str] = []
        self.meta_datas: dict[str, str] = {}
        self.jsonld: list[str] = []
        self._no_ld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "link" and "canonical" in a.get("rel", "").lower().split() and not self.canonical:
            self.canonical = a.get("href", "").strip()
        elif tag == "meta":
            nome = (a.get("name") or a.get("property") or a.get("itemprop") or "").lower()
            if nome in ("robots", "googlebot"):
                self.robots.append(a.get("content", "").lower())
            elif nome in ("article:modified_time", "og:updated_time", "datemodified", "last-modified"):
                self.meta_datas.setdefault(nome, a.get("content", "").strip())
        elif tag == "script" and "ld+json" in a.get("type", "").lower():
            self._no_ld, self._buf = True, []

    def handle_data(self, data):
        if self._no_ld:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._no_ld:
            self.jsonld.append("".join(self._buf))
            self._no_ld = False


def normaliza_url(u: str) -> str:
    p = urlparse(u.strip())
    netloc = p.netloc.lower()
    if (p.scheme == "https" and netloc.endswith(":443")) or (p.scheme == "http" and netloc.endswith(":80")):
        netloc = netloc.rsplit(":", 1)[0]
    return urlunparse((p.scheme.lower(), netloc, p.path or "/", "", p.query, ""))


def date_modified_jsonld(blocos: list[str], url: str) -> str:
    """dateModified do nó principal: o que casa com a URL, senão o de WebPage/Article, senão o primeiro."""
    achados: list[tuple[int, str]] = []
    alvo = normaliza_url(url)

    def visita(no):
        if isinstance(no, list):
            for x in no:
                visita(x)
        elif isinstance(no, dict):
            if isinstance(no.get("dateModified"), str):
                ident = str(no.get("@id") or no.get("url") or "")
                tipo = no.get("@type")
                tipos = tipo if isinstance(tipo, list) else [tipo]
                prioridade = 2
                if ident and normaliza_url(ident.split("#")[0]) == alvo:
                    prioridade = 0
                elif any(t in ("WebPage", "Article", "BlogPosting", "NewsArticle", "ProfilePage",
                               "CollectionPage", "AboutPage", "FAQPage", "ItemPage") for t in tipos):
                    prioridade = 1
                achados.append((prioridade, no["dateModified"]))
            for v in no.values():
                if isinstance(v, (dict, list)):
                    visita(v)

    for b in blocos:
        try:
            visita(json.loads(b))
        except (ValueError, TypeError):
            continue
    return min(achados)[1] if achados else ""


def verifica(cli: Cliente, e: Entrada, tolerancia: float) -> None:
    v: dict = {}
    r = cli.get(e.loc, redirecionar=False)
    if r is None:
        e.problemas.append(("FAIL", "sem resposta (erro de rede ou 429)"))
        return
    v["status"] = r.status_code
    if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
        destino = urljoin(e.loc, r.headers.get("Location", ""))
        v["redireciona_para"] = destino
        e.problemas.append(("FAIL", f"redireciona ({r.status_code}) para {destino}"))
        e.verificacao = v
        return
    if r.status_code != 200:
        e.problemas.append(("FAIL", f"responde {r.status_code}"))
        e.verificacao = v
        return
    xrobots = r.headers.get("X-Robots-Tag", "").lower()
    lm_header = r.headers.get("Last-Modified", "")
    v["last_modified_header"] = lm_header
    if "html" in r.headers.get("Content-Type", "").lower():
        r.encoding = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else r.apparent_encoding
        leitor = LeitorHead()
        try:
            leitor.feed(r.text)
        except Exception:  # noqa: BLE001
            pass
        v["canonical"] = urljoin(e.loc, leitor.canonical) if leitor.canonical else ""
        v["article_modified"] = leitor.meta_datas.get("article:modified_time", "") or \
            leitor.meta_datas.get("og:updated_time", "") or leitor.meta_datas.get("datemodified", "")
        v["jsonld_modified"] = date_modified_jsonld(leitor.jsonld, e.loc)
        noindex = any("noindex" in x or "none" == x.strip() for x in leitor.robots) or "noindex" in xrobots
    else:
        v["canonical"] = v["article_modified"] = v["jsonld_modified"] = ""
        noindex = "noindex" in xrobots
    v["noindex"] = noindex
    if noindex:
        e.problemas.append(("FAIL", "noindex (meta robots ou X-Robots-Tag) em URL listada no sitemap"))
    if v["canonical"] and normaliza_url(v["canonical"]) != normaliza_url(e.loc):
        e.problemas.append(("FAIL", f"canonical aponta para outra URL: {v['canonical']}"))

    dt_sitemap = parse_w3c(e.lastmod) if e.lastmod else None
    so_data = bool(e.lastmod) and "T" not in e.lastmod
    maior = None
    v["datas_comparadas"] = 0
    v["header_diverge"] = ""
    if dt_sitemap:
        def diferenca(dt: datetime) -> float:
            if so_data:  # lastmod só com data: compara no nível do dia
                return abs((dt.date() - dt_sitemap.date()).days)
            return abs((dt - dt_sitemap).total_seconds()) / 86400

        fontes = [("dateModified do JSON-LD", v["jsonld_modified"]),
                  ("meta de data modificada", v["article_modified"])]
        for rotulo, bruto in fontes:
            dt = parse_data_livre(bruto) if bruto else None
            if not dt:
                continue
            diff = diferenca(dt)
            v["datas_comparadas"] += 1
            maior = diff if maior is None else max(maior, diff)
            if diff > tolerancia:
                e.problemas.append(("ATENÇÃO", f"lastmod {e.lastmod} difere {diff:.1f} dia(s) do {rotulo} ({bruto})"))
        # o header Last-Modified de CMS com cache costuma ser a hora do cache:
        # só vira ATENÇÃO quando a página não traz data própria
        dt_h = _parse_http_date(lm_header) if lm_header else None
        if dt_h:
            diff = diferenca(dt_h)
            if diff > tolerancia:
                v["header_diverge"] = f"{diff:.1f}"
                if v["datas_comparadas"] == 0:
                    v["datas_comparadas"] = 1
                    maior = diff if maior is None else max(maior, diff)
                    e.problemas.append(("ATENÇÃO", f"lastmod {e.lastmod} difere {diff:.1f} dia(s) do header "
                                                   f"Last-Modified ({lm_header}), e a página não traz data própria"))
            elif v["datas_comparadas"] == 0:
                v["datas_comparadas"] = 1
                maior = diff
    v["maior_divergencia_dias"] = round(maior, 2) if maior is not None else ""
    e.verificacao = v


def _parse_http_date(valor: str) -> datetime | None:
    try:
        d = parsedate_to_datetime(valor)
    except (TypeError, ValueError, IndexError):
        return None
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------
def chave_mesma_data(valor: str) -> str:
    """Normaliza para comparar 'o mesmo lastmod': data e hora até o segundo em UTC, ou só a data."""
    dt = parse_w3c(valor)
    if not dt:
        return valor
    return dt.strftime("%Y-%m-%d") if "T" not in valor else dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def audita(entradas: list[Entrada], same_ratio: float, min_urls: int, agora: datetime) -> list[str]:
    """Checagens sem rede. Devolve alertas globais (nível agregado)."""
    alertas: list[str] = []
    for e in entradas:
        if not e.lastmod:
            e.problemas.append(("ATENÇÃO", "sem <lastmod>"))
            continue
        dt = parse_w3c(e.lastmod)
        if not dt:
            e.problemas.append(("FAIL", f"lastmod fora do formato W3C Datetime: {e.lastmod!r}"))
            continue
        folga = timedelta(hours=14) if "T" not in e.lastmod else timedelta(minutes=5)
        if dt > agora + folga:
            e.problemas.append(("FAIL", f"lastmod no futuro: {e.lastmod}"))

    def mesma_data(grupo: list[Entrada], rotulo: str) -> None:
        validas = [e for e in grupo if e.lastmod and parse_w3c(e.lastmod)]
        if len(validas) < min_urls:
            return
        valor, qtd = Counter(chave_mesma_data(e.lastmod) for e in validas).most_common(1)[0]
        frac = qtd / len(validas)
        if frac >= same_ratio:
            alertas.append(f"ATENÇÃO  {rotulo}: {qtd} de {len(validas)} URLs ({frac:.0%}) com o mesmo lastmod "
                           f"{valor} (sinal de lastmod gerado no build)")
            for e in validas:
                if chave_mesma_data(e.lastmod) == valor:
                    e.problemas.append(("ATENÇÃO", f"lastmod repetido em {frac:.0%} das URLs de {rotulo}"))

    mesma_data(entradas, "sitemap inteiro")
    por_sitemap: dict[str, list[Entrada]] = defaultdict(list)
    for e in entradas:
        por_sitemap[e.sitemap].append(e)
    if len(por_sitemap) > 1:
        for sm, grupo in por_sitemap.items():
            mesma_data(grupo, sm)
    for sm, grupo in por_sitemap.items():
        li = grupo[0].lastmod_index
        if not li or len(grupo) < 2:
            continue
        chave_li = chave_mesma_data(li)
        if all(e.lastmod and chave_mesma_data(e.lastmod) == chave_li for e in grupo):
            alertas.append(f"ATENÇÃO  {sm}: todas as {len(grupo)} URLs têm o lastmod igual ao do sitemap index ({li})")
            for e in grupo:
                e.problemas.append(("ATENÇÃO", "lastmod idêntico ao do sitemap index"))
    return alertas


def main() -> None:
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="Audita o <lastmod> de um sitemap e, com --verify, confere a amostra ao vivo.")
    ap.add_argument("sitemap", nargs="?", default="", help="URL do sitemap, sitemap index (.xml ou .xml.gz) ou robots.txt")
    ap.add_argument("--file", default="", help="sitemap local (.xml ou .xml.gz) em vez de URL")
    ap.add_argument("--same-ratio", type=float, default=0.5,
                    help="fração de URLs com o mesmo lastmod que gera alerta (padrão 0.5)")
    ap.add_argument("--min-urls", type=int, default=5, help="mínimo de URLs em um grupo para o alerta de mesmo lastmod (padrão 5)")
    ap.add_argument("--verify", action="store_true", help="baixa uma amostra e compara com a página")
    ap.add_argument("--sample", type=int, default=20, help="tamanho da amostra do --verify (padrão 20)")
    ap.add_argument("--seed", type=int, default=42, help="semente da amostra aleatória (padrão 42)")
    ap.add_argument("--tolerance-days", type=float, default=2, help="divergência tolerada em dias (padrão 2)")
    ap.add_argument("--delay", type=float, default=1.0, help="segundos entre requisições (padrão 1.0)")
    ap.add_argument("--max-urls", type=int, default=50000, help="máximo de URLs lidas do sitemap (padrão 50000)")
    ap.add_argument("--show", type=int, default=10, help="exemplos por checagem no terminal (padrão 10)")
    ap.add_argument("--csv", default="", help="grava uma linha por URL em CSV")
    ap.add_argument("--strict", action="store_true", help="código de saída 1 se houver ATENÇÃO ou FAIL")
    args = ap.parse_args()

    if bool(args.sitemap) == bool(args.file):
        ap.error("informe a URL do sitemap ou --file (um dos dois)")

    cli = Cliente(args.delay)
    erros: list[tuple[str, str]] = []

    def obter(url: str) -> bytes | None:
        if args.file and url == args.file:
            with open(url, "rb") as fh:
                return fh.read()
        if not url.startswith(("http://", "https://")):
            erros.append((url, "sitemap filho sem URL absoluta"))
            return None
        r = cli.get(url)
        if r is None:
            return None
        if r.status_code != 200:
            erros.append((url, f"sitemap respondeu {r.status_code}"))
            return None
        return r.content

    entradas: list[Entrada] = []
    origem = args.file or args.sitemap
    le_sitemap(obter, origem, entradas, erros, set())
    vistos: set[str] = set()
    unicas = []
    repetidas: list[str] = []
    for e in entradas:
        if e.loc not in vistos:
            vistos.add(e.loc)
            unicas.append(e)
        else:
            repetidas.append(e.loc)
    duplicadas = len(repetidas)
    entradas = unicas[: args.max_urls]
    if not entradas:
        print("Nenhuma URL encontrada no sitemap.", file=sys.stderr)
        for u, m in erros + cli.erros:
            print(f"  {u}: {m}", file=sys.stderr)
        sys.exit(2)

    agora = datetime.now(timezone.utc)
    alertas = audita(entradas, args.same_ratio, args.min_urls, agora)

    amostra: list[Entrada] = []
    if args.verify:
        rnd = random.Random(args.seed)
        amostra = rnd.sample(entradas, min(args.sample, len(entradas)))
        for i, e in enumerate(amostra, 1):
            print(f"  [{i}/{len(amostra)}] {e.loc}", file=sys.stderr)
            verifica(cli, e, args.tolerance_days)

    # ---------------- relatório ----------------
    sitemaps = sorted({e.sitemap for e in entradas})
    com = [e for e in entradas if e.lastmod]
    print(f"\n=== {NOME}: {origem} ===")
    print(f"{len(entradas)} URL(s) em {len(sitemaps)} sitemap(s) | com lastmod: {len(com)} "
          f"({len(com) / len(entradas):.0%}) | URLs repetidas no sitemap: {duplicadas}")
    for u in repetidas[: args.show]:
        print(f"  ATENÇÃO  URL listada mais de uma vez: {u}")
    datas = sorted(parse_w3c(e.lastmod) for e in com if parse_w3c(e.lastmod))
    if datas:
        print(f"lastmod mais antigo: {datas[0]:%Y-%m-%d} | mais recente: {datas[-1]:%Y-%m-%d} | "
              f"hoje (UTC): {agora:%Y-%m-%d}")

    def lista(titulo: str, filtro) -> int:
        itens = [(e, txt) for e in entradas for nivel, txt in e.problemas if filtro(nivel, txt)]
        if not itens:
            return 0
        print(f"\n{titulo}: {len(itens)}")
        for e, txt in itens[: args.show]:
            print(f"  {e.loc}\n      {txt}")
        if len(itens) > args.show:
            print(f"  ... e mais {len(itens) - args.show}")
        return len(itens)

    print()
    for a in alertas:
        print(a)
    lista("FAIL  lastmod fora do formato W3C Datetime", lambda n, t: t.startswith("lastmod fora"))
    lista("FAIL  lastmod no futuro", lambda n, t: t.startswith("lastmod no futuro"))
    sem = sum(1 for e in entradas if not e.lastmod)
    if sem:
        print(f"\nATENÇÃO  sem <lastmod>: {sem} URL(s)")
        for e in [e for e in entradas if not e.lastmod][: args.show]:
            print(f"  {e.loc}")
    if args.verify:
        print(f"\nVerificação ao vivo: amostra de {len(amostra)} URL(s), tolerância {args.tolerance_days:g} dia(s)")
        limpas = [e for e in amostra if e.verificacao.get("status") == 200
                  and not any(n == "FAIL" for n, _ in e.problemas)]
        comparaveis = [e for e in limpas if e.verificacao.get("datas_comparadas")]
        coerentes = [e for e in comparaveis if not any("difere" in t for _, t in e.problemas)]
        print(f"  200, indexável e com canonical própria: {len(limpas)} | com data para comparar: "
              f"{len(comparaveis)} | lastmod coerente com a página: {len(coerentes)}")
        so_header = [e for e in amostra if e.verificacao.get("header_diverge")
                     and not any("header" in t for _, t in e.problemas)]
        if so_header:
            print(f"  {len(so_header)} URL(s) com header Last-Modified fora da tolerância, mas com data própria "
                  "coerente na página (header de cache, informativo)")
        lista("FAIL  status, redirecionamento, canonical ou noindex",
              lambda n, t: n == "FAIL" and any(t.startswith(x) for x in
                                               ("responde", "redireciona", "canonical", "noindex", "sem resposta")))
        lista("ATENÇÃO  lastmod diverge da página", lambda n, t: "difere" in t)
        sem_data = [e for e in amostra if e.verificacao.get("status") == 200 and not any(
            e.verificacao.get(k) for k in ("jsonld_modified", "article_modified", "last_modified_header"))]
        if sem_data:
            print(f"\n  {len(sem_data)} URL(s) da amostra sem data nenhuma na página nem no header para comparar:")
            for e in sem_data[: args.show]:
                print(f"    {e.loc}")
    else:
        print("\n(Sem --verify: só checagens do arquivo. Use --verify --sample N para comparar com as páginas.)")
    todas_falhas = erros + cli.erros
    if todas_falhas:
        print("\nFalhas de leitura:")
        for u, m in todas_falhas[:20]:
            print(f"  {u}: {m}")

    n_fail = sum(1 for e in entradas for n, _ in e.problemas if n == "FAIL")
    n_atencao = sum(1 for e in entradas for n, _ in e.problemas if n == "ATENÇÃO")
    print(f"\nResumo: FAIL {n_fail} | ATENÇÃO {n_atencao} | URLs sem problema: "
          f"{sum(1 for e in entradas if not e.problemas)} de {len(entradas)}")
    print("(Limiares ajustáveis. O Google não publica percentual de lastmod repetido nem tolerância em dias.)")

    if args.csv:
        campos = ["url", "sitemap", "lastmod", "lastmod_index", "status", "redireciona_para", "canonical", "noindex",
                  "last_modified_header", "article_modified", "jsonld_modified", "maior_divergencia_dias",
                  "header_diverge_dias",
                  "nivel", "problemas"]
        with open(args.csv, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=campos)
            w.writeheader()
            for e in entradas:
                niveis = {n for n, _ in e.problemas}
                v = e.verificacao
                w.writerow({
                    "url": e.loc, "sitemap": e.sitemap, "lastmod": e.lastmod or "",
                    "lastmod_index": e.lastmod_index or "", "status": v.get("status", ""),
                    "redireciona_para": v.get("redireciona_para", ""), "canonical": v.get("canonical", ""),
                    "noindex": v.get("noindex", ""), "last_modified_header": v.get("last_modified_header", ""),
                    "article_modified": v.get("article_modified", ""), "jsonld_modified": v.get("jsonld_modified", ""),
                    "maior_divergencia_dias": v.get("maior_divergencia_dias", ""),
                    "header_diverge_dias": v.get("header_diverge", ""),
                    "nivel": "FAIL" if "FAIL" in niveis else ("ATENÇÃO" if niveis else "OK"),
                    "problemas": " ; ".join(t for _, t in e.problemas),
                })
        print(f"CSV: {args.csv}")

    if args.strict and (n_fail or n_atencao or alertas or repetidas):
        sys.exit(1)


if __name__ == "__main__":
    main()
