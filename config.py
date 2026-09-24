"""
Configuração central do scraper de terrenos.
Edite SITES para adicionar/remover fontes, e CRITERIA para mudar os filtros.
"""
import os

# ---------------------------------------------------------------------------
# Critérios de filtro
# ---------------------------------------------------------------------------
CRITERIA = {
    "price_min": 150_000,
    "price_max": 300_000,
    "area_priority_min": 350,  # >= isso vira "⭐ prioritário" na notificação
}

# ---------------------------------------------------------------------------
# WhatsApp (endpoint da própria A Modo Mio)
# ---------------------------------------------------------------------------
WHATSAPP_API_URL = "https://www.amodomio.com.br/api/messages/text"
WHATSAPP_API_KEY = os.environ.get("AMODOMIO_API_KEY", "")
WHATSAPP_TARGET_PHONE = os.environ.get("TARGET_PHONE", "")  # ex: 5546999999999

# ---------------------------------------------------------------------------
# Intervalo entre execuções (em minutos)
# ---------------------------------------------------------------------------
SCRAPE_INTERVAL_MINUTES = int(os.environ.get("SCRAPE_INTERVAL_MINUTES", "240"))

# ---------------------------------------------------------------------------
# Caminho do banco de dedupe (SQLite)
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("DB_PATH", "/data/listings.db")

# ---------------------------------------------------------------------------
# Sites monitorados
#   platform: qual parser usar (ver scraper/sites/)
#     olx, imovelweb, zap, chavesnamao, imb, trovit, generic, single_listing
# ---------------------------------------------------------------------------
SITES = [
    {"name": "OLX - Terrenos/Lotes", "url": "https://www.olx.com.br/imoveis/terrenos/lotes/estado-pr/regiao-de-francisco-beltrao-e-pato-branco/pato-branco", "platform": "olx"},
    {"name": "OLX - Terrenos (geral)", "url": "https://www.olx.com.br/imoveis/terrenos/estado-pr/regiao-de-francisco-beltrao-e-pato-branco/pato-branco", "platform": "olx"},
    {"name": "OLX - Fraron", "url": "https://www.olx.com.br/imoveis/terrenos/estado-pr/regiao-de-francisco-beltrao-e-pato-branco/pato-branco/fraron", "platform": "olx"},
    {"name": "ImovelWeb - Pato Branco", "url": "https://www.imovelweb.com.br/terrenos-venda-pato-branco-pr.html", "platform": "imovelweb"},
    {"name": "ImovelWeb - São Luiz", "url": "https://www.imovelweb.com.br/terrenos-venda-sao-luiz-pato-branco.html", "platform": "imovelweb"},
    {"name": "Zap Imóveis", "url": "https://www.zapimoveis.com.br/venda/terrenos-lotes-condominios/pr+pato-branco/", "platform": "zap"},
    {"name": "Chaves na Mão", "url": "https://www.chavesnamao.com.br/terrenos-a-venda/pr-pato-branco/", "platform": "chavesnamao"},
    {"name": "Chaves na Mão - Aeroporto", "url": "https://www.chavesnamao.com.br/terrenos-a-venda/pr-pato-branco/aeroporto/", "platform": "chavesnamao"},
    {"name": "Conceito PB - Terreno", "url": "https://www.conceitopbimoveis.com.br/filtro/list/todos/terreno/todas/todos---todos/0-3000000/todos/todos/1", "platform": "generic"},
    {"name": "Conceito PB - Terreno Comercial", "url": "https://www.conceitopbimoveis.com.br/filtro/list/todos/terreno-comercial/todas/todos---todos/0-3000000/todos/todos/1", "platform": "generic"},
    {"name": "Rafa Imóveis", "url": "https://rafaimoveis.com/venda/vendas-terrenos", "platform": "generic"},
    {"name": "Solar Imóveis", "url": "https://solar.imb.br/venda/vendas-terrenos", "platform": "imb"},
    {"name": "Apolar", "url": "https://www.apolar.com.br/venda/terreno/pato-branco", "platform": "generic"},
    {"name": "Famex Imóveis", "url": "https://fameximoveis.com.br/imoveis-venda", "platform": "generic"},
    {"name": "Ciro Imóveis PB", "url": "https://www.ciroimoveispb.com.br/filtro/list/todos/casa/todas/todos/0-10000000/todos/7", "platform": "generic"},
    {"name": "Imobiliária Trento", "url": "https://www.imobiliariatrento.com.br/resultado-busca2.asp?cat1=1&cat3=8", "platform": "generic"},
    {"name": "Imobiliária Moretti", "url": "https://www.imobiliariamoretti.imb.br/pt-BR/imoveis/?categoria=terreno", "platform": "imb"},
    {"name": "Assmann Imóveis", "url": "https://www.assmannimoveis.com.br/pato-branco/25", "platform": "generic"},
    {"name": "Imobilli", "url": "https://imobilli.imb.br/venda/vendas-terrenos", "platform": "imb"},
    {"name": "Invest Imóveis PB", "url": "https://www.investimoveispatobranco.com.br/filtro/list/venda/terreno/todas----todos/todos----todos----todos/0-10000000----0-10000000/todos/1/asc", "platform": "generic"},
    {"name": "Cristian Imóveis", "url": "https://cristianimoveis.com.br/c/3/terrenos", "platform": "generic"},
    {"name": "To Em Casa", "url": "https://toemcasa.com.br/venda/terreno/pato-branco-pr/", "platform": "generic"},
    {"name": "Trovit", "url": "https://imoveis.trovit.com.br/terreno-pato-branco-centro", "platform": "trovit"},
    {"name": "Realiza PB", "url": "https://realizapb.com.br/venda/vendas-terrenos", "platform": "imb"},
    {"name": "Cad Imobiliária", "url": "https://www.cadimobiliaria.com.br/imoveis/venda/terrenos/65/1/1", "platform": "generic"},
    {"name": "MGF Imóveis", "url": "https://www.mgfimoveis.com.br/venda/terreno-lote/pr-pato-branco", "platform": "generic"},
    # Anúncios individuais (não são listas de busca — monitorados por mudança de preço/disponibilidade)
    {"name": "Aliança PB - anúncio 958", "url": "https://aliancapbimoveis.com.br/imoveis-venda/958-terreno-para-venda-alvorada-pato-branco-te958", "platform": "single_listing"},
    {"name": "Ciro Imóveis - Monte Belo", "url": "https://www.ciroimoveispb.com.br/imovel/venda/terreno/pato-branco-pr/loteamento-monte-belo-i-e-ii/terreno--loteamento-monte-belo-i-e-ii--pato-branco---pr/614184", "platform": "single_listing"},
    {"name": "Trento - próx. PB Shopping", "url": "https://www.imobiliariatrento.com.br/imovel/venda/terreno/pato-branco-pr/sao-francisco/terreno-a-venda-proximo-ao-pb-shopping--pato-branco---pr-/732215", "platform": "single_listing"},
]
