"""
Chaves na Mão — parser dedicado. Cada anúncio é um <div id="rc-<id>"> com:
  - <a href="/imovel/..." title="..."> (link + título)
  - <p class="...addressStreet..."> rua e <p class="...addressCity..."> "Bairro, Pato Branco/PR"
  - <p aria-label="... Área útil"> "577m²"
  - <p aria-label="Preço"><b>R$ 285.000</b></p>
As classes têm sufixo com hash (CSS modules), por isso os seletores usam [class*=...].

A lista é paginada (?pg=N, 15 por página) e aceita filtro de preço na URL
(?filtro=pmin:X,pmax:Y) — ver o site em config.py.
"""
from ..base import Listing, absolute_url, parse_area, parse_price


def parse(html: str, base_url: str, site_name: str) -> list[Listing]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    listings: list[Listing] = []
    seen_urls = set()

    for card in soup.select('div[id^="rc-"]'):
        link = card.find("a", href=True)
        if not link or "/imovel/" not in link["href"]:
            continue
        url = absolute_url(base_url, link["href"])
        if url in seen_urls:
            continue

        price_tag = card.select_one('[aria-label="Preço"]')
        price = parse_price(price_tag.get_text(" ", strip=True)) if price_tag else None
        if price is None:
            continue  # "Consulte" / sem preço

        title_tag = card.find("h2")
        title = (title_tag.get_text(" ", strip=True) if title_tag else "") or link.get("title") or site_name

        area_tag = card.select_one('[aria-label*="Área"]')
        area = parse_area(area_tag.get_text("", strip=True)) if area_tag else None

        # "Vila Isabel, Pato Branco/PR" -> "Vila Isabel"
        city_tag = card.select_one('[class*="addressCity"]')
        city_text = (city_tag.get("title") or city_tag.get_text(" ", strip=True)) if city_tag else ""
        bairro = city_text.split(",")[0].strip() if "," in city_text else ""

        street_tag = card.select_one('[class*="addressStreet"]')
        street = street_tag.get_text(" ", strip=True) if street_tag else ""

        seen_urls.add(url)
        listings.append(
            Listing(
                site=site_name,
                title=title[:140],
                url=url,
                price=price,
                area=area,
                location=bairro,
                description=street[:160],
                raw_text=card.get_text(" ", strip=True)[:500],
            )
        )

    return listings
