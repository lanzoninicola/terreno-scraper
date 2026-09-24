"""
Servidor web mínimo que renderiza o relatório de terrenos direto do SQLite,
a cada acesso (sem gerar arquivo estático). Roda como serviço separado no
docker-compose ("web"), lendo o mesmo /data/listings.db que o "scraper"
escreve.
"""
from datetime import datetime, timezone

from flask import Flask, Response

from config import DB_PATH, CRITERIA
from scraper.storage import get_all_listings

app = Flask(__name__)


def fmt_money(v):
    if v is None:
        return "—"
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def fmt_area(v):
    if v is None:
        return "—"
    return f"{v:,.0f} m²".replace(",", ".")


def fmt_date(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%d/%m %H:%M")


CARD_TMPL = """
<a class="card{priority_class}" href="{url}" target="_blank" rel="noopener">
  <div class="card-top">
    <span class="site">{site}</span>
    <span class="date">{date}</span>
  </div>
  <div class="title">{title}</div>
  <div class="meta">
    <span class="price">{price}</span>
    <span class="area">{area}</span>
  </div>
</a>
"""

PAGE_TMPL = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Terrenos — Pato Branco</title>
<style>
  :root {{
    --bg: #0b0c0f;
    --card: #16181d;
    --border: #262931;
    --text: #e8e9ec;
    --muted: #8b8f99;
    --accent: #f2c94c;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    padding: env(safe-area-inset-top,0) 0 env(safe-area-inset-bottom,0);
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  header {{
    padding: 20px 16px 12px;
    border-bottom: 1px solid var(--border);
  }}
  h1 {{ margin: 0 0 4px; font-size: 20px; }}
  .sub {{ color: var(--muted); font-size: 13px; }}
  main {{ padding: 12px 16px 40px; max-width: 640px; margin: 0 auto; }}
  .card {{
    display: block;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 10px;
    text-decoration: none;
    color: var(--text);
  }}
  .card.priority {{ border-color: var(--accent); }}
  .card-top {{
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 6px;
  }}
  .title {{ font-size: 15px; margin-bottom: 8px; line-height: 1.3; }}
  .meta {{ display: flex; gap: 14px; font-size: 14px; }}
  .price {{ font-weight: 600; }}
  .area {{ color: var(--muted); }}
  .empty {{ color: var(--muted); text-align: center; padding: 40px 0; }}
</style>
</head>
<body>
<header>
  <h1>Terrenos em Pato Branco</h1>
  <div class="sub">R$ {price_min} – {price_max} · {count} encontrados · atualizado {now}</div>
</header>
<main>
{cards}
</main>
</body>
</html>
"""


@app.route("/")
def report():
    listings = get_all_listings(DB_PATH)

    if not listings:
        cards_html = '<div class="empty">Nenhum terreno encontrado ainda.</div>'
    else:
        parts = []
        for l in listings:
            priority = l["area"] is not None and l["area"] >= CRITERIA["area_priority_min"]
            parts.append(
                CARD_TMPL.format(
                    priority_class=" priority" if priority else "",
                    url=l["url"],
                    site=l["site"],
                    date=fmt_date(l["first_seen"]),
                    title=l["title"],
                    price=fmt_money(l["last_price"] or l["price"]),
                    area=fmt_area(l["area"]),
                )
            )
        cards_html = "\n".join(parts)

    html = PAGE_TMPL.format(
        price_min=f"{CRITERIA['price_min']:,.0f}".replace(",", "."),
        price_max=f"{CRITERIA['price_max']:,.0f}".replace(",", "."),
        count=len(listings),
        now=datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC"),
        cards=cards_html,
    )
    return Response(html, mimetype="text/html")


@app.route("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
