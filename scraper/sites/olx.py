"""
OLX renderiza a lista praticamente pronta no HTML (SSR), então dá pra usar
a extração genérica. A única particularidade é que quando o anúncio tem
desconto, aparecem DOIS preços no bloco (o riscado e o atual) — pegamos o
menor dos dois, que é sempre o preço vigente.
"""
import re

from ..base import Listing, generic_extract, PRICE_RE, parse_area


def parse(html: str, base_url: str, site_name: str) -> list[Listing]:
    listings = generic_extract(html, base_url, site_name)

    # corrige preço quando há "de/por" (preço riscado + preço atual) no mesmo bloco
    fixed = []
    for lst in listings:
        prices = [float(p.replace(".", "")) for p in PRICE_RE.findall(lst.raw_text)]
        if len(prices) > 1:
            lst.price = min(prices)
        if lst.area is None:
            lst.area = parse_area(lst.raw_text)
        fixed.append(lst)
    return fixed
