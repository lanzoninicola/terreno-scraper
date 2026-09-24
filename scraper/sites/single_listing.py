"""
Para URLs que já são um anúncio específico (não uma lista de busca).
Aqui não faz sentido "detectar novo anúncio" — o que monitoramos é:
  - se o anúncio ainda está no ar (título encontrado)
  - se o preço mudou desde a última checagem
O storage.py trata isso comparando o preço salvo com o preço atual.
"""
from bs4 import BeautifulSoup

from ..base import Listing, parse_price, parse_area


def parse(html: str, base_url: str, site_name: str) -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    title_tag = soup.find(["h1", "title"])
    title = title_tag.get_text(" ", strip=True) if title_tag else site_name

    price = parse_price(text)
    area = parse_area(text)

    if price is None:
        return []

    return [
        Listing(
            site=site_name,
            title=title[:140],
            url=base_url,
            price=price,
            area=area,
            raw_text=text[:500],
        )
    ]
