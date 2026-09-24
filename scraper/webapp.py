"""
Servidor web mínimo que renderiza o relatório de terrenos direto do SQLite,
a cada acesso (sem gerar arquivo estático). Roda como serviço separado no
docker-compose ("web"), lendo o mesmo /data/listings.db que o "scraper"
escreve.
"""
from datetime import datetime, timezone
import threading

from flask import Flask, Response, request, jsonify

from config import DB_PATH, CRITERIA
from scraper.storage import (
    get_all_listings, set_status, set_favorite,
    get_excluded_bairros, set_bairro_excluded,
    try_start_run, finish_run,
)

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
<div class="card{priority_class}" data-uid="{uid_attr}" data-price="{price_raw}"
     data-bairro="{bairro_attr}" data-status="{status_attr}" data-favorite="{favorite_attr}">
  <div class="card-top">
    <span class="site">{site}{bairro_badge}</span>
    <span class="date">{date}</span>
  </div>
  <a class="title" href="{url}" target="_blank" rel="noopener">{title}</a>
  {description_html}
  <div class="meta">
    <span class="price">{price}</span>
    <span class="area">{area}</span>
  </div>
  <div class="actions">
    <button class="btn btn-fav" data-uid="{uid_attr}">☆</button>
    <button class="btn btn-seen" data-uid="{uid_attr}">👁 Já visto</button>
    <button class="btn btn-dismiss" data-uid="{uid_attr}">✕ Não interessa</button>
    {exclude_bairro_btn}
  </div>
</div>
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
    --ok: #4caf7d;
    --off: #4b4f58;
    --fav: #f2994a;
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
    padding: 16px 16px 12px;
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: env(safe-area-inset-top, 0);
    background: var(--bg);
    z-index: 5;
  }}
  h1 {{ margin: 0 0 4px; font-size: 20px; }}
  .sub {{ color: var(--muted); font-size: 13px; margin-bottom: 12px; }}
  .legend {{ color: var(--muted); font-size: 12px; margin-bottom: 12px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
  .legend .dot {{ width: 10px; height: 10px; border-radius: 3px; border: 2px solid var(--accent); display: inline-block; }}
  .filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
  .filters input, .filters select {{
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
    flex: 1;
    min-width: 90px;
  }}
  .toggle-row {{ display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); margin-bottom: 6px; }}
  main {{ padding: 12px 16px 40px; max-width: 640px; margin: 0 auto; }}
  .group-header {{
    color: var(--muted);
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin: 18px 0 8px;
    padding-bottom: 4px;
    border-bottom: 1px solid var(--border);
  }}
  .group-header:first-child {{ margin-top: 0; }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
    margin-bottom: 10px;
  }}
  .card.priority {{ border-color: var(--accent); border-width: 2px; }}
  .card[data-status="seen"] {{ opacity: 0.55; }}
  .card[data-status="dismissed"] {{ opacity: 0.35; }}
  .card-top {{
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: var(--muted);
    margin-bottom: 6px;
  }}
  .title {{
    display: block;
    font-size: 15px;
    margin-bottom: 4px;
    line-height: 1.3;
    color: var(--text);
    text-decoration: none;
  }}
  .desc {{ font-size: 13px; color: var(--muted); margin-bottom: 8px; line-height: 1.35; }}
  .meta {{ display: flex; gap: 14px; font-size: 14px; margin-bottom: 10px; }}
  .price {{ font-weight: 600; }}
  .area {{ color: var(--muted); }}
  .actions {{ display: flex; gap: 8px; }}
  .btn {{
    flex: 1;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    border-radius: 8px;
    padding: 7px 8px;
    font-size: 12px;
  }}
  .btn-fav {{ flex: none; width: 36px; font-size: 16px; line-height: 1; }}
  .btn-fav.active {{ border-color: var(--fav); color: var(--fav); }}
  .btn-seen.active {{ border-color: var(--ok); color: var(--ok); }}
  .btn-dismiss.active {{ border-color: var(--off); color: var(--text); }}
  .btn-exclude-bairro {{ flex: none; padding: 7px 10px; }}
  .empty {{ color: var(--muted); text-align: center; padding: 40px 0; }}
  .count {{ color: var(--muted); font-size: 12px; margin: 4px 0 10px; }}
  .excluded-panel {{ margin-top: 4px; }}
  .chips {{ display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; min-height: 14px; }}
  .chip {{
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--muted);
    border-radius: 999px;
    padding: 4px 10px 4px 12px;
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .chip button {{
    background: none; border: none; color: var(--muted); font-size: 13px; padding: 0; cursor: pointer;
  }}
  .chips-empty {{ color: var(--muted); font-size: 12px; opacity: 0.6; }}
</style>
</head>
<body>
<header>
  <h1>Terrenos em Pato Branco</h1>
  <div class="sub">R$ {price_min} – {price_max} · {count} encontrados · atualizado {now}</div>
  <button class="btn" id="btn-force-run" style="margin-bottom:10px;width:100%">🔄 Forçar nova busca agora</button>
  <div class="toggle-row" id="force-run-status" style="margin-bottom:10px"></div>
  <div class="legend"><span class="dot"></span> contorno amarelo = terreno prioritário (≥ {area_priority} m²)</div>
  <div class="filters">
    <input id="f-min" type="number" placeholder="Preço mín." inputmode="numeric">
    <input id="f-max" type="number" placeholder="Preço máx." inputmode="numeric">
    <select id="f-bairro"><option value="">Todos os bairros</option>{bairro_options}</select>
  </div>
  <div class="filters">
    <select id="f-group">
      <option value="none">Não agrupar</option>
      <option value="bairro">Agrupar por bairro</option>
      <option value="price">Agrupar por faixa de preço</option>
    </select>
  </div>
  <label class="toggle-row">
    <input type="checkbox" id="f-hide-dismissed" checked> ocultar "não interessa"
  </label>
  <label class="toggle-row">
    <input type="checkbox" id="f-only-fav"> mostrar somente favoritos ★
  </label>
  <div class="excluded-panel">
    <div class="toggle-row" style="margin-bottom:0">bairros excluídos:</div>
    <div class="chips" id="excluded-chips">{excluded_chips}</div>
  </div>
</header>
<main>
  <div class="count" id="count-label"></div>
  <div id="cards">
{cards}
  </div>
</main>
<script>
  const cardsEl = Array.from(document.querySelectorAll('.card'));
  const cardsContainer = document.getElementById('cards');
  const fMin = document.getElementById('f-min');
  const fMax = document.getElementById('f-max');
  const fBairro = document.getElementById('f-bairro');
  const fHideDismissed = document.getElementById('f-hide-dismissed');
  const fOnlyFav = document.getElementById('f-only-fav');
  const fGroup = document.getElementById('f-group');
  const countLabel = document.getElementById('count-label');

  function updateButtons(card) {{
    const status = card.dataset.status || '';
    const fav = card.dataset.favorite === '1';
    card.querySelector('.btn-seen').classList.toggle('active', status === 'seen');
    card.querySelector('.btn-dismiss').classList.toggle('active', status === 'dismissed');
    const favBtn = card.querySelector('.btn-fav');
    favBtn.classList.toggle('active', fav);
    favBtn.textContent = fav ? '★' : '☆';
  }}
  cardsEl.forEach(updateButtons);

  function bairroKey(c) {{ return c.dataset.bairro || 'Sem bairro'; }}
  function priceBucketKey(c) {{
    const p = parseFloat(c.dataset.price) || 0;
    const size = 50000;
    const lower = Math.floor(p / size) * size;
    const upper = lower + size;
    const fmt = v => 'R$ ' + v.toLocaleString('pt-BR');
    return fmt(lower) + ' – ' + fmt(upper);
  }}

  function regroup(visibleCards) {{
    cardsContainer.querySelectorAll('.group-header').forEach(h => h.remove());
    const mode = fGroup.value;

    if (mode === 'none') {{
      visibleCards.forEach(c => cardsContainer.appendChild(c));
      return;
    }}

    const keyFn = mode === 'bairro' ? bairroKey : priceBucketKey;
    const groups = new Map();
    visibleCards.forEach(c => {{
      const k = keyFn(c);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(c);
    }});
    const sortedKeys = Array.from(groups.keys()).sort((a, b) => {{
      if (mode === 'price') {{
        return parseFloat(a.replace(/\\D/g, '')) - parseFloat(b.replace(/\\D/g, ''));
      }}
      return a.localeCompare(b, 'pt-BR');
    }});
    sortedKeys.forEach(k => {{
      const header = document.createElement('div');
      header.className = 'group-header';
      header.textContent = k + ' (' + groups.get(k).length + ')';
      cardsContainer.appendChild(header);
      groups.get(k).forEach(c => cardsContainer.appendChild(c));
    }});
  }}

  function applyFilters() {{
    const min = parseFloat(fMin.value) || 0;
    const max = parseFloat(fMax.value) || Infinity;
    const bairro = fBairro.value;
    const hideDismissed = fHideDismissed.checked;
    const onlyFav = fOnlyFav.checked;
    const visibleCards = [];
    cardsEl.forEach(c => {{
      const price = parseFloat(c.dataset.price) || 0;
      const cBairro = c.dataset.bairro || '';
      const status = c.dataset.status || '';
      const fav = c.dataset.favorite === '1';
      let ok = price >= min && price <= max && (!bairro || cBairro === bairro);
      if (hideDismissed && status === 'dismissed') ok = false;
      if (onlyFav && !fav) ok = false;
      c.style.display = ok ? 'block' : 'none';
      if (ok) visibleCards.push(c);
    }});
    countLabel.textContent = visibleCards.length + ' de ' + cardsEl.length + ' terrenos';
    regroup(visibleCards);
  }}
  [fMin, fMax, fBairro, fHideDismissed, fOnlyFav, fGroup].forEach(
    el => el.addEventListener('input', applyFilters)
  );
  applyFilters();

  async function setStatus(uid, status) {{
    try {{
      await fetch('/api/status', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{uid, status}}),
      }});
    }} catch (e) {{ console.error(e); }}
  }}

  async function setFavorite(uid, favorite) {{
    try {{
      await fetch('/api/favorite', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{uid, favorite}}),
      }});
    }} catch (e) {{ console.error(e); }}
  }}

  cardsContainer.addEventListener('click', (ev) => {{
    const btn = ev.target.closest('.btn');
    if (!btn) return;

    if (btn.classList.contains('btn-exclude-bairro')) {{
      excludeBairro(btn.dataset.bairro, true);
      return;
    }}

    const card = btn.closest('.card');
    const uid = btn.dataset.uid;

    if (btn.classList.contains('btn-fav')) {{
      const nextFav = card.dataset.favorite !== '1';
      card.dataset.favorite = nextFav ? '1' : '0';
      updateButtons(card);
      setFavorite(uid, nextFav);
      applyFilters();
      return;
    }}

    const current = card.dataset.status || '';
    const clicked = btn.classList.contains('btn-seen') ? 'seen' : 'dismissed';
    const next = current === clicked ? '' : clicked;  // clicar de novo desfaz
    card.dataset.status = next;
    updateButtons(card);
    setStatus(uid, next);
    applyFilters();
  }});

  async function excludeBairro(bairro, excluded) {{
    try {{
      await fetch('/api/exclude-bairro', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{bairro, excluded}}),
      }});
    }} catch (e) {{ console.error(e); }}
    window.location.reload();
  }}

  document.getElementById('excluded-chips').addEventListener('click', (ev) => {{
    const btn = ev.target.closest('button');
    if (!btn) return;
    excludeBairro(btn.dataset.bairro, false);
  }});

  const btnForceRun = document.getElementById('btn-force-run');
  const forceRunStatus = document.getElementById('force-run-status');
  btnForceRun.addEventListener('click', async () => {{
    btnForceRun.disabled = true;
    forceRunStatus.textContent = 'Iniciando busca em todos os sites...';
    try {{
      const resp = await fetch('/api/force-run', {{ method: 'POST' }});
      const data = await resp.json();
      if (data.ok) {{
        forceRunStatus.textContent = 'Busca em andamento — pode levar alguns minutos. Recarregue a página depois pra ver o resultado (o WhatsApp avisa se achar algo novo).';
      }} else {{
        forceRunStatus.textContent = data.error || 'Já tem uma busca em andamento.';
      }}
    }} catch (e) {{
      forceRunStatus.textContent = 'Erro ao iniciar a busca.';
    }}
    setTimeout(() => {{ btnForceRun.disabled = false; }}, 15000);
  }});
</script>
</body>
</html>
"""


@app.route("/")
def report():
    listings = get_all_listings(DB_PATH)
    excluded_bairros = get_excluded_bairros(DB_PATH)
    excluded_set = {b.lower() for b in excluded_bairros}

    # bairros excluídos não aparecem na lista/filtro — só no painel de gerenciamento (recuperáveis)
    visible_listings = [
        l for l in listings
        if not (l.get("location") and l["location"].lower() in excluded_set)
    ]

    bairros = sorted({l["location"] for l in visible_listings if l.get("location")})
    bairro_options = "".join(f'<option value="{b}">{b}</option>' for b in bairros)

    if excluded_bairros:
        excluded_chips = "".join(
            f'<span class="chip">{b} <button data-bairro="{b}">✕</button></span>'
            for b in excluded_bairros
        )
    else:
        excluded_chips = '<span class="chips-empty">nenhum</span>'

    if not visible_listings:
        cards_html = '<div class="empty">Nenhum terreno encontrado ainda.</div>'
    else:
        parts = []
        for l in visible_listings:
            priority = l["area"] is not None and l["area"] >= CRITERIA["area_priority_min"]
            bairro = l.get("location") or ""
            description = (l.get("description") or "").strip()
            description_html = f'<div class="desc">{description}</div>' if description else ""
            bairro_badge = f" · {bairro}" if bairro else ""
            price_val = l["last_price"] if l["last_price"] is not None else l["price"]
            exclude_bairro_btn = (
                f'<button class="btn btn-exclude-bairro" data-bairro="{bairro}" '
                f'title="Excluir bairro {bairro}">🚫 {bairro}</button>'
                if bairro else ""
            )
            parts.append(
                CARD_TMPL.format(
                    priority_class=" priority" if priority else "",
                    uid_attr=l["uid"],
                    price_raw=price_val or 0,
                    bairro_attr=bairro,
                    status_attr=l.get("status") or "",
                    favorite_attr=1 if l.get("favorite") else 0,
                    url=l["url"],
                    site=l["site"],
                    bairro_badge=bairro_badge,
                    date=fmt_date(l["first_seen"]),
                    title=l["title"],
                    description_html=description_html,
                    price=fmt_money(price_val),
                    area=fmt_area(l["area"]),
                    exclude_bairro_btn=exclude_bairro_btn,
                )
            )
        cards_html = "\n".join(parts)

    html = PAGE_TMPL.format(
        price_min=f"{CRITERIA['price_min']:,.0f}".replace(",", "."),
        price_max=f"{CRITERIA['price_max']:,.0f}".replace(",", "."),
        area_priority=f"{CRITERIA['area_priority_min']:,.0f}".replace(",", "."),
        count=len(visible_listings),
        now=datetime.now(timezone.utc).strftime("%d/%m %H:%M UTC"),
        cards=cards_html,
        bairro_options=bairro_options,
        excluded_chips=excluded_chips,
    )
    return Response(html, mimetype="text/html")


@app.route("/api/exclude-bairro", methods=["POST"])
def api_exclude_bairro():
    data = request.get_json(silent=True) or {}
    bairro = (data.get("bairro") or "").strip()
    excluded = bool(data.get("excluded"))
    if not bairro:
        return jsonify({"ok": False, "error": "bairro obrigatório"}), 400
    current = set_bairro_excluded(DB_PATH, bairro, excluded)
    return jsonify({"ok": True, "excluded_bairros": current})


@app.route("/api/status", methods=["POST"])
def api_status():
    data = request.get_json(silent=True) or {}
    uid = data.get("uid", "")
    status = data.get("status", "")
    if status not in ("", "seen", "dismissed"):
        return jsonify({"ok": False, "error": "status inválido"}), 400
    if not uid:
        return jsonify({"ok": False, "error": "uid obrigatório"}), 400
    ok = set_status(DB_PATH, uid, status)
    return jsonify({"ok": ok})


@app.route("/api/favorite", methods=["POST"])
def api_favorite():
    data = request.get_json(silent=True) or {}
    uid = data.get("uid", "")
    favorite = bool(data.get("favorite"))
    if not uid:
        return jsonify({"ok": False, "error": "uid obrigatório"}), 400
    ok = set_favorite(DB_PATH, uid, favorite)
    return jsonify({"ok": ok})


def _background_run():
    try:
        from main import run_once  # import tardio: evita custo de import no boot do web
        run_once(notify_always=True)
    finally:
        finish_run(DB_PATH)


@app.route("/api/force-run", methods=["POST"])
def api_force_run():
    started = try_start_run(DB_PATH)
    if not started:
        return jsonify({"ok": False, "error": "Já tem uma busca em andamento."}), 409
    threading.Thread(target=_background_run, daemon=True).start()
    return jsonify({"ok": True, "started": True})


@app.route("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
