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


@dataclass
class Listing:
    site: str
    title: str
    url: str
    price: float | None = None
    area: float | None = None
    location: str = ""
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
                raw_text=block_text[:500],
            )
        )

    return listings
