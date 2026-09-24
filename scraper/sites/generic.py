"""
Parser genérico — usado como está para: generic, imovelweb, zap, chavesnamao,
imb, trovit. Todos esses sites seguem o padrão comum de cards com preço "R$"
e metragem "m²" perto de um link de anúncio, então a heurística de base.py
cobre bem sem precisar de seletor CSS específico por site.

Se algum site desses vier com poucos/nenhum resultado, o ajuste fino é
plugar um parser dedicado em scraper/sites/<nome>.py com seletores CSS reais
(inspecionando o HTML do site já rodando, o que dá pra fazer direto no VPS
com o Playwright em modo não-headless ou via view-source).
"""
from ..base import Listing, generic_extract


def parse(html: str, base_url: str, site_name: str) -> list[Listing]:
    return generic_extract(html, base_url, site_name)
