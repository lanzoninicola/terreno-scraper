"""
Funções compartilhadas por todos os parsers de site.
"""
import re
import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

logger = logging.getLogger("scraper")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

PRICE_RE = re.compile(r"R\$\s*([\d\.]{2,})")
AREA_RE = re.compile(r"([\d\.]+(?:,\d+)?)\s*m²")
# "Pato Branco, Aeroporto" ou "Aeroporto, Pato Branco" — pega o bairro nos dois formatos
LOCATION_RE = re.compile(
    r"(?:Pato Branco,\s*([A-ZÀ-Ú][\wÀ-ú\s]{2,30})|([A-ZÀ-Ú][\wÀ-ú\s]{2,30}),\s*Pato Branco)"
)


@dataclass
class Listing:
    site: str
    title: str
    url: str
    price: float | None = None
    area: float | None = None
    location: str = ""
    description: str = ""
    raw_text: str = field(default="", repr=False)

    @property
    def uid(self) -> str:
        # chave estável para dedupe: prioriza a URL do anúncio
        return self.url or f"{self.site}|{self.title}|{self.price}"


def parse_price(text: str) -> float | None:
    m = PRICE_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_area(text: str) -> float | None:
    m = AREA_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_location(text: str) -> str:
    m = LOCATION_RE.search(text or "")
    if not m:
        return ""
    bairro = (m.group(1) or m.group(2) or "").strip(" ,.-")
    return bairro


def make_description(block_text: str, title: str) -> str:
    """Tira preço/área/título do texto do bloco e devolve um resumo curto."""
    text = PRICE_RE.sub(" ", block_text or "")
    text = AREA_RE.sub(" ", text)
    if title:
        text = text.replace(title, " ")
    text = re.sub(r"\s+", " ", text).strip(" -,.")
    return text[:160]


def fetch_html(url: str, wait_ms: int = 2500) -> str:
    """Renderiza a página com Playwright (cobre sites JS-pesados) e devolve o HTML final."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="pt-BR")
        try:
            page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            html = page.content()
        except Exception as e:
            logger.warning("Falha ao carregar %s: %s", url, e)
            html = ""
        finally:
            browser.close()
        return html


def absolute_url(base: str, href: str) -> str:
    if not href:
        return ""
    return urljoin(base, href)


def generic_extract(html: str, base_url: str, site_name: str) -> list[Listing]:
    """
    Heurística genérica: acha blocos de texto que tenham 'R$' e opcionalmente 'm²'
    próximos de um link, e monta um Listing a partir disso.
    Serve de fallback para sites sem parser dedicado — e para a maioria dos
    sites locais/pequenos, que costumam seguir esse padrão (preço + metragem + link).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []
    seen_urls = set()

    # candidatos: qualquer container que tenha um preço "R$" dentro dele
    for node in soup.find_all(string=PRICE_RE):
        container = node.parent
        # sobe até achar um bloco com um link de anúncio (heurística: sobe até 5 níveis)
        block = container
        link_tag = None
        for _ in range(6):
            if block is None:
                break
            link_tag = block.find("a", href=True)
            if link_tag:
                break
            block = block.parent

        if not link_tag:
            continue

        href = absolute_url(base_url, link_tag.get("href", ""))
        if not href or href in seen_urls:
            continue

        block_text = block.get_text(" ", strip=True) if block else str(node)
        price = parse_price(block_text)
        area = parse_area(block_text)
        title = link_tag.get("title") or link_tag.get_text(" ", strip=True) or site_name

        if price is None:
            continue

        seen_urls.add(href)
        listings.append(
            Listing(
                site=site_name,
                title=title[:140],
                url=href,
                price=price,
                area=area,
                location=parse_location(block_text),
                description=make_description(block_text, title),
                raw_text=block_text[:500],
            )
        )

    return listings
