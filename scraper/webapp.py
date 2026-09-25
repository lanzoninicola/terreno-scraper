"""
Servidor web mínimo que renderiza o relatório de terrenos direto do SQLite,
a cada acesso (sem gerar arquivo estático). Roda como serviço separado no
docker-compose ("web"), lendo o mesmo /data/listings.db que o "scraper"
escreve.
"""
import html
import threading
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, request, jsonify

from config import DB_PATH, CRITERIA
from scraper.storage import (
    get_all_listings, set_status, set_favorite, set_visit, mark_clicked,
    get_excluded_bairros, set_bairro_excluded,
    get_last_new_uids, try_start_run, finish_run,
)

app = Flask(__name__)


def esc(v) -> str:
    return html.escape(str(v) if v is not None else "", quote=True)


def fmt_money(v):
    if v is None:
        return "—"
    return "R$ " + f"{v:,.0f}".replace(",", ".")


def fmt_money_short(v):
    """Abreviação em K: 300000 -> '300K', 292162 -> '292K' (arredonda ao milhar)."""
    if v is None:
        return "—"
    k = round(v / 1000)
    return f"{k}K"


def fmt_area(v):
    if v is None:
        return "—"
    return f"{v:,.0f} m²".replace(",", ".")


# horário de Brasília/São Paulo (UTC-3, sem horário de verão desde 2019)
TZ_BR = timezone(timedelta(hours=-3))


def fmt_date(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=TZ_BR).strftime("%d/%m %H:%M")


CARD_TMPL = """
<div class="card{priority_class}{new_class}" data-uid="{uid_attr}" data-price="{price_raw}"
     data-bairro="{bairro_attr}" data-status="{status_attr}" data-favorite="{favorite_attr}" data-visit="{visit_attr}"
     data-new="{new_attr}"
     data-title="{title_attr}" data-desc="{desc_attr}" data-site="{site_attr}"
     data-url="{url_attr}" data-price-full="{price_full_attr}" data-area-full="{area_full_attr}"
     data-date-full="{date_attr}">
  {new_badge}
  <button class="icon-btn btn-dismiss" data-uid="{uid_attr}" title="Não interessa" aria-label="Não interessa">✕</button>
  <div class="card-price">{price_short}</div>
  <div class="card-sub"><span class="card-area">{area}</span> · {date}</div>
  <div class="card-bairro">{bairro}</div>
  <div class="actions">
    <button class="icon-btn btn-fav" data-uid="{uid_attr}" title="Favoritar">☆</button>
    <button class="icon-btn btn-visit" data-uid="{uid_attr}" title="Quero visitar">📅</button>
    <button class="icon-btn btn-seen" data-uid="{uid_attr}" title="Já visto">👁</button>
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
    --new: #56ccf2;
    --visit: #bb86fc;
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
  .header-row {{ display: flex; justify-content: space-between; align-items: center; gap: 8px; }}
  h1 {{ margin: 0; font-size: 20px; }}
  .sub {{ color: var(--muted); font-size: 13px; margin: 4px 0 10px; }}
  .tabs {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }}
  .tab-link {{
    color: var(--muted);
    text-decoration: none;
    font-size: 13px;
    padding: 6px 12px;
    border-radius: 999px;
    border: 1px solid var(--border);
  }}
  .tab-link.active {{ color: var(--text); border-color: var(--accent); }}
  .btn-toggle-filters {{
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    white-space: nowrap;
  }}
  #btn-force-run {{
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 12px;
    width: 100%;
    margin-bottom: 8px;
  }}
  #filters-panel {{ display: none; }}
  #filters-panel.open {{ display: block; }}
  .legend {{ color: var(--muted); font-size: 12px; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }}
  .legend .dot {{ width: 10px; height: 10px; border-radius: 3px; border: 2px solid var(--accent); display: inline-block; }}
  .filters {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 8px; }}
  .filters input, .filters select {{
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 15px;
    flex: 1;
    min-width: 90px;
  }}
  .toggle-row {{ display: flex; align-items: center; gap: 6px; font-size: 14px; color: var(--muted); margin-bottom: 6px; }}
  main {{ padding: 12px 16px 40px; max-width: 720px; margin: 0 auto; }}
  .group-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
  details.group-acc {{ margin-bottom: 14px; }}
  details.group-acc summary {{
    color: var(--text);
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.01em;
    padding: 6px 0 8px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 10px;
    cursor: pointer;
    list-style: revert;
  }}
  .card {{
    position: relative;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 12px;
    cursor: pointer;
  }}
  .card.priority {{ border-color: var(--accent); border-width: 2px; }}
  .card.is-new {{ border-color: var(--new); }}
  .card[data-status="seen"] {{ opacity: 0.55; }}
  .card[data-status="dismissed"] {{ opacity: 0.35; }}
  .new-badge {{
    position: absolute;
    top: -7px;
    left: 8px;
    background: var(--new);
    color: #04181d;
    font-size: 10px;
    font-weight: 700;
    padding: 2px 7px;
    border-radius: 999px;
    letter-spacing: 0.03em;
  }}
  .card-price {{ font-size: 20px; font-weight: 700; margin-bottom: 4px; padding-right: 24px; }}
  .card-sub {{ font-size: 12px; color: var(--muted); margin-bottom: 2px; line-height: 1.3; }}
  .card-area {{ font-size: 15px; font-weight: 600; color: var(--text); }}
  .card-bairro {{ font-size: 12px; color: var(--muted); margin-bottom: 10px; line-height: 1.3; min-height: 1.3em;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .actions {{ display: flex; gap: 6px; }}
  .icon-btn {{
    flex: 1;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    border-radius: 8px;
    padding: 6px 0;
    font-size: 14px;
    line-height: 1;
  }}
  .btn-fav.active {{ border-color: var(--fav); color: var(--fav); }}
  .btn-visit.active {{ border-color: var(--visit); background: color-mix(in srgb, var(--visit) 18%, transparent); }}
  #modal-visit-toggle.active {{ border-color: var(--visit); color: var(--visit); }}
  .btn-seen.active {{ border-color: var(--ok); color: var(--ok); }}
  .icon-btn.btn-dismiss {{
    position: absolute;
    top: 4px;
    right: 4px;
    flex: none;
    width: 28px;
    height: 28px;
    padding: 0;
    border: none;
    border-radius: 999px;
    font-size: 14px;
  }}
  .btn-dismiss:hover {{ background: var(--border); color: var(--text); }}
  .btn-dismiss.active {{ background: var(--off); color: var(--text); }}
  .empty {{ color: var(--muted); text-align: center; padding: 40px 0; grid-column: 1 / -1; }}
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

  /* modal */
  #modal-overlay {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.6);
    z-index: 20;
    padding: 16px;
    align-items: flex-end;
    justify-content: center;
  }}
  #modal-overlay.open {{ display: flex; }}
  #modal {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px 16px 0 0;
    padding: 20px 18px calc(20px + env(safe-area-inset-bottom,0));
    width: 100%;
    max-width: 480px;
    max-height: 82vh;
    overflow-y: auto;
  }}
  #modal .modal-top {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 8px; }}
  #modal .modal-close {{ background: none; border: none; color: var(--muted); font-size: 20px; padding: 0 4px; }}
  #modal .modal-site {{ color: var(--muted); font-size: 12px; margin-bottom: 2px; }}
  #modal .modal-source {{ color: var(--muted); font-size: 13px; margin-bottom: 12px; }}
  #modal .modal-source strong {{ color: var(--text); font-weight: 600; }}
  #modal .modal-title {{ font-size: 17px; font-weight: 600; margin-bottom: 10px; line-height: 1.35; }}
  #modal .modal-meta {{ display: flex; gap: 16px; font-size: 15px; margin-bottom: 12px; }}
  #modal .modal-meta .price {{ font-weight: 700; }}
  #modal .modal-desc {{ font-size: 13px; color: var(--muted); line-height: 1.5; margin-bottom: 16px; white-space: pre-line; }}
  #modal .modal-visit-btn {{
    display: block;
    text-align: center;
    background: var(--accent);
    color: #1a1500;
    font-weight: 700;
    text-decoration: none;
    border-radius: 10px;
    padding: 13px;
    margin-bottom: 10px;
    font-size: 14px;
  }}
  #modal .modal-actions {{ display: flex; gap: 8px; margin-bottom: 8px; }}
  #modal .modal-actions .icon-btn {{ font-size: 12px; padding: 9px 0; }}
  #modal .modal-exclude {{
    display: block;
    width: 100%;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--muted);
    border-radius: 8px;
    padding: 9px;
    font-size: 12px;
  }}
</style>
</head>
<body>
<header>
  <div class="header-row">
    <h1>Terrenos em Pato Branco</h1>
    <button class="btn-toggle-filters" id="btn-toggle-filters">🔍 Filtrar busca</button>
  </div>
  <div class="sub">R$ {price_min} – {price_max} · {count} encontrados · atualizado {now}</div>
  <div class="tabs">
    <a class="tab-link{tab_all_active}" href="/">Todos</a>
    <a class="tab-link{tab_fav_active}" href="/favoritos">★ Favoritos</a>
    <a class="tab-link{tab_clicked_active}" href="/abertos">↗ Abertos</a>
    <a class="tab-link{tab_visits_active}" href="/visitas">📅 Visitas</a>
  </div>
  <button id="btn-force-run">🔄 Forçar nova busca agora</button>
  <div class="toggle-row" id="force-run-status"></div>

  <div id="filters-panel">
    <div class="legend"><span class="dot"></span> contorno amarelo = prioritário (≥ {area_priority} m²) · <span style="color:var(--new)">●</span> azul = novo desde a última busca</div>
    <div class="filters">
      <input id="f-min" type="number" placeholder="Preço mín." inputmode="numeric">
      <input id="f-max" type="number" placeholder="Preço máx." inputmode="numeric">
      <select id="f-bairro" style="flex-basis: 100%;"><option value="">Todos os bairros</option>{bairro_options}</select>
    </div>
    <div class="filters">
      <select id="f-group" autocomplete="off">
        <option value="none">Não agrupar</option>
        <option value="bairro">Agrupar por bairro</option>
        <option value="price" selected>Agrupar por faixa de preço</option>
      </select>
    </div>
    <label class="toggle-row">
      <input type="checkbox" id="f-show-dismissed" autocomplete="off"> mostrar "não interessa" (<span id="dismissed-count">0</span>)
    </label>
    <label class="toggle-row">
      <input type="checkbox" id="f-only-new" autocomplete="off"> mostrar somente novos 🆕
    </label>
    <div class="excluded-panel">
      <div class="toggle-row" style="margin-bottom:0">bairros excluídos:</div>
      <div class="chips" id="excluded-chips">{excluded_chips}</div>
    </div>
  </div>
</header>
<main>
  <div class="count" id="count-label"></div>
  <div id="cards">
{cards}
  </div>
</main>

<div id="modal-overlay">
  <div id="modal">
    <div class="modal-top">
      <div>
        <div class="modal-site" id="modal-site"></div>
        <div class="modal-title" id="modal-title"></div>
      </div>
      <button class="modal-close" id="modal-close">✕</button>
    </div>
    <div class="modal-meta">
      <span class="price" id="modal-price"></span>
      <span id="modal-area"></span>
    </div>
    <div class="modal-source">Fonte: <strong id="modal-source"></strong></div>
    <div class="modal-desc" id="modal-desc"></div>
    <a class="modal-visit-btn" id="modal-visit" target="_blank" rel="noopener">Ver anúncio no site →</a>
    <div class="modal-actions">
      <button class="icon-btn" id="modal-fav">☆ Favoritar</button>
      <button class="icon-btn" id="modal-visit-toggle">📅 Visitar</button>
      <button class="icon-btn" id="modal-seen">👁 Já visto</button>
      <button class="icon-btn" id="modal-dismiss">✕ Não interessa</button>
    </div>
    <button class="modal-exclude" id="modal-exclude"></button>
  </div>
</div>

<script>
  const cardsEl = Array.from(document.querySelectorAll('.card'));
  const cardsContainer = document.getElementById('cards');
  const fMin = document.getElementById('f-min');
  const fMax = document.getElementById('f-max');
  const fBairro = document.getElementById('f-bairro');
  const fShowDismissed = document.getElementById('f-show-dismissed');
  const dismissedCount = document.getElementById('dismissed-count');
  const fOnlyNew = document.getElementById('f-only-new');
  const fGroup = document.getElementById('f-group');
  const countLabel = document.getElementById('count-label');

  const btnToggleFilters = document.getElementById('btn-toggle-filters');
  const filtersPanel = document.getElementById('filters-panel');
  btnToggleFilters.addEventListener('click', () => {{
    const open = filtersPanel.classList.toggle('open');
    btnToggleFilters.textContent = open ? '✕ Fechar' : '🔍 Filtrar busca';
  }});

  function updateButtons(card) {{
    const status = card.dataset.status || '';
    const fav = card.dataset.favorite === '1';
    card.querySelector('.btn-seen').classList.toggle('active', status === 'seen');
    card.querySelector('.btn-dismiss').classList.toggle('active', status === 'dismissed');
    const favBtn = card.querySelector('.btn-fav');
    favBtn.classList.toggle('active', fav);
    favBtn.textContent = fav ? '★' : '☆';
    card.querySelector('.btn-visit').classList.toggle('active', card.dataset.visit === '1');
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

  // acordeões começam fechados; lembra os abertos pra não fecharem a cada applyFilters()
  const openGroups = new Set();

  function regroup(visibleCards) {{
    cardsContainer.innerHTML = '';
    const mode = fGroup.value;

    if (mode === 'none') {{
      const grid = document.createElement('div');
      grid.className = 'group-grid';
      visibleCards.forEach(c => grid.appendChild(c));
      cardsContainer.appendChild(grid);
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
      const det = document.createElement('details');
      det.className = 'group-acc';
      det.open = openGroups.has(mode + ':' + k);
      det.addEventListener('toggle', () => {{
        if (det.open) openGroups.add(mode + ':' + k); else openGroups.delete(mode + ':' + k);
      }});
      const sum = document.createElement('summary');
      sum.textContent = k + ' (' + groups.get(k).length + ')';
      det.appendChild(sum);
      const grid = document.createElement('div');
      grid.className = 'group-grid';
      groups.get(k).forEach(c => grid.appendChild(c));
      det.appendChild(grid);
      cardsContainer.appendChild(det);
    }});
  }}

  function applyFilters() {{
    const min = parseFloat(fMin.value) || 0;
    const max = parseFloat(fMax.value) || Infinity;
    const bairro = fBairro.value;
    const showDismissed = fShowDismissed.checked;
    let nDismissed = 0;
    const onlyNew = fOnlyNew.checked;
    const visibleCards = [];
    cardsEl.forEach(c => {{
      const price = parseFloat(c.dataset.price) || 0;
      const cBairro = c.dataset.bairro || '';
      const status = c.dataset.status || '';
      const isNew = c.dataset.new === '1';
      let ok = price >= min && price <= max && (!bairro || cBairro === bairro);
      if (status === 'dismissed') {{
        nDismissed++;
        if (!showDismissed) ok = false;
      }}
      if (onlyNew && !isNew) ok = false;
      c.style.display = ok ? 'block' : 'none';
      if (ok) visibleCards.push(c);
    }});
    dismissedCount.textContent = nDismissed;
    countLabel.textContent = visibleCards.length + ' de ' + cardsEl.length + ' terrenos';
    regroup(visibleCards);
  }}
  [fMin, fMax, fBairro, fShowDismissed, fOnlyNew, fGroup].forEach(
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

  async function setVisit(uid, visit) {{
    try {{
      await fetch('/api/visit', {{
        method: 'POST',
        headers: {{'Content-Type': 'application/json'}},
        body: JSON.stringify({{uid, visit}}),
      }});
    }} catch (e) {{ console.error(e); }}
  }}

  function markClicked(uid) {{
    // sendBeacon sobrevive à troca de aba/navegação; fetch keepalive como fallback
    const body = new Blob([JSON.stringify({{uid}})], {{type: 'application/json'}});
    try {{
      if (!(navigator.sendBeacon && navigator.sendBeacon('/api/click', body))) {{
        fetch('/api/click', {{method: 'POST', body, keepalive: true,
          headers: {{'Content-Type': 'application/json'}}}});
      }}
    }} catch (e) {{ console.error(e); }}
  }}

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

  // ---- ações rápidas nos ícones do card + abrir modal ----
  cardsContainer.addEventListener('click', (ev) => {{
    const iconBtn = ev.target.closest('.icon-btn');
    const card = ev.target.closest('.card');
    if (!card) return;
    const uid = card.dataset.uid;

    if (iconBtn) {{
      if (iconBtn.classList.contains('btn-fav')) {{
        const nextFav = card.dataset.favorite !== '1';
        card.dataset.favorite = nextFav ? '1' : '0';
        updateButtons(card);
        setFavorite(uid, nextFav);
        applyFilters();
        return;
      }}
      if (iconBtn.classList.contains('btn-visit')) {{
        const nextVisit = card.dataset.visit !== '1';
        card.dataset.visit = nextVisit ? '1' : '0';
        updateButtons(card);
        setVisit(uid, nextVisit);
        return;
      }}
      const current = card.dataset.status || '';
      const clicked = iconBtn.classList.contains('btn-seen') ? 'seen' : 'dismissed';
      const next = current === clicked ? '' : clicked;
      card.dataset.status = next;
      updateButtons(card);
      setStatus(uid, next);
      applyFilters();
      return;
    }}

    openModal(card);
  }});

  // ---- modal ----
  const modalOverlay = document.getElementById('modal-overlay');
  const modalSite = document.getElementById('modal-site');
  const modalSource = document.getElementById('modal-source');
  const modalTitle = document.getElementById('modal-title');
  const modalPrice = document.getElementById('modal-price');
  const modalArea = document.getElementById('modal-area');
  const modalDesc = document.getElementById('modal-desc');
  const modalVisit = document.getElementById('modal-visit');
  const modalFav = document.getElementById('modal-fav');
  const modalVisitToggle = document.getElementById('modal-visit-toggle');
  const modalSeen = document.getElementById('modal-seen');
  const modalDismiss = document.getElementById('modal-dismiss');
  const modalExclude = document.getElementById('modal-exclude');
  let modalCard = null;

  modalVisit.addEventListener('click', () => {{
    if (modalCard) markClicked(modalCard.dataset.uid);
  }});

  function openModal(card) {{
    modalCard = card;
    const bairro = card.dataset.bairro || '';
    modalSite.textContent = bairro;
    let host = '';
    try {{ host = new URL(card.dataset.url).hostname.replace(/^www\\./, ''); }} catch (e) {{}}
    modalSource.textContent = card.dataset.site + (host ? ' (' + host + ')' : '');
    modalTitle.textContent = card.dataset.title;
    modalPrice.textContent = card.dataset.priceFull;
    modalArea.textContent = card.dataset.areaFull + ' · ' + card.dataset.dateFull;
    modalDesc.textContent = card.dataset.desc || 'Sem descrição disponível.';
    modalVisit.href = card.dataset.url;
    modalExclude.textContent = bairro ? ('🚫 Excluir bairro ' + bairro) : '';
    modalExclude.style.display = bairro ? 'block' : 'none';
    updateModalButtons();
    modalOverlay.classList.add('open');
  }}
  function closeModal() {{
    modalOverlay.classList.remove('open');
    modalCard = null;
  }}
  function updateModalButtons() {{
    if (!modalCard) return;
    const status = modalCard.dataset.status || '';
    const fav = modalCard.dataset.favorite === '1';
    modalFav.textContent = fav ? '★ Favorito' : '☆ Favoritar';
    modalFav.classList.toggle('active', fav);
    const visit = modalCard.dataset.visit === '1';
    modalVisitToggle.textContent = visit ? '📅 Na lista' : '📅 Visitar';
    modalVisitToggle.classList.toggle('active', visit);
    modalSeen.classList.toggle('active', status === 'seen');
    modalDismiss.classList.toggle('active', status === 'dismissed');
  }}

  document.getElementById('modal-close').addEventListener('click', closeModal);
  modalOverlay.addEventListener('click', (ev) => {{ if (ev.target === modalOverlay) closeModal(); }});

  modalFav.addEventListener('click', () => {{
    if (!modalCard) return;
    const nextFav = modalCard.dataset.favorite !== '1';
    modalCard.dataset.favorite = nextFav ? '1' : '0';
    updateButtons(modalCard);
    updateModalButtons();
    setFavorite(modalCard.dataset.uid, nextFav);
    applyFilters();
  }});
  modalVisitToggle.addEventListener('click', () => {{
    if (!modalCard) return;
    const nextVisit = modalCard.dataset.visit !== '1';
    modalCard.dataset.visit = nextVisit ? '1' : '0';
    updateButtons(modalCard);
    updateModalButtons();
    setVisit(modalCard.dataset.uid, nextVisit);
  }});
  modalSeen.addEventListener('click', () => {{
    if (!modalCard) return;
    const next = (modalCard.dataset.status === 'seen') ? '' : 'seen';
    modalCard.dataset.status = next;
    updateButtons(modalCard);
    updateModalButtons();
    setStatus(modalCard.dataset.uid, next);
    applyFilters();
  }});
  modalDismiss.addEventListener('click', () => {{
    if (!modalCard) return;
    const next = (modalCard.dataset.status === 'dismissed') ? '' : 'dismissed';
    modalCard.dataset.status = next;
    updateButtons(modalCard);
    updateModalButtons();
    setStatus(modalCard.dataset.uid, next);
    applyFilters();
  }});
  modalExclude.addEventListener('click', () => {{
    if (!modalCard) return;
    const bairro = modalCard.dataset.bairro;
    if (bairro) excludeBairro(bairro, true);
  }});

  // ---- forçar nova busca ----
  const btnForceRun = document.getElementById('btn-force-run');
  const forceRunStatus = document.getElementById('force-run-status');
  btnForceRun.addEventListener('click', async () => {{
    btnForceRun.disabled = true;
    forceRunStatus.textContent = 'Iniciando busca em todos os sites...';
    try {{
      const resp = await fetch('/api/force-run', {{ method: 'POST' }});
      const data = await resp.json();
      if (data.ok) {{
        forceRunStatus.textContent = 'Busca em andamento — pode levar alguns minutos. Recarregue a página depois pra ver o resultado (o WhatsApp avisa quando terminar).';
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


def render_page(view: str = "all") -> str:
    listings = get_all_listings(DB_PATH, view=view)
    excluded_bairros = get_excluded_bairros(DB_PATH)
    excluded_set = {b.lower() for b in excluded_bairros}
    new_uids = set(get_last_new_uids(DB_PATH))

    # bairros excluídos não aparecem na lista/filtro — só no painel de gerenciamento (recuperáveis)
    visible_listings = [
        l for l in listings
        if not (l.get("location") and l["location"].lower() in excluded_set)
    ]

    bairros = sorted({l["location"] for l in visible_listings if l.get("location")})
    bairro_options = "".join(f'<option value="{esc(b)}">{esc(b)}</option>' for b in bairros)

    if excluded_bairros:
        excluded_chips = "".join(
            f'<span class="chip">{esc(b)} <button data-bairro="{esc(b)}">✕</button></span>'
            for b in excluded_bairros
        )
    else:
        excluded_chips = '<span class="chips-empty">nenhum</span>'

    if not visible_listings:
        empty_msg = {
            "favorites": "Nenhum favorito ainda.",
            "clicked": "Nenhum anúncio aberto ainda.",
            "visits": "Nenhuma visita marcada ainda.",
        }.get(view, "Nenhum terreno encontrado ainda.")
        cards_html = f'<div class="empty">{empty_msg}</div>'
    else:
        parts = []
        for l in visible_listings:
            priority = l["area"] is not None and l["area"] >= CRITERIA["area_priority_min"]
            is_new = l["uid"] in new_uids
            bairro = l.get("location") or ""
            description = (l.get("description") or "").strip()
            price_val = l["last_price"] if l["last_price"] is not None else l["price"]
            parts.append(
                CARD_TMPL.format(
                    priority_class=" priority" if priority else "",
                    new_class=" is-new" if is_new else "",
                    uid_attr=esc(l["uid"]),
                    price_raw=price_val or 0,
                    bairro_attr=esc(bairro),
                    bairro=esc(bairro),
                    status_attr=esc(l.get("status") or ""),
                    favorite_attr=1 if l.get("favorite") else 0,
                    visit_attr=1 if l.get("visit") else 0,
                    new_attr=1 if is_new else 0,
                    title_attr=esc(l["title"]),
                    desc_attr=esc(description),
                    site_attr=esc(l["site"]),
                    url_attr=esc(l["url"]),
                    price_full_attr=esc(fmt_money(price_val)),
                    area_full_attr=esc(fmt_area(l["area"])),
                    date_attr=esc(fmt_date(l["first_seen"])),
                    new_badge='<span class="new-badge">NOVO</span>' if is_new else "",
                    price_short=esc(fmt_money_short(price_val)),
                    area=esc(fmt_area(l["area"])),
                    date=esc(
                        "aberto " + fmt_date(l["clicked_at"]) if view == "clicked"
                        else fmt_date(l["first_seen"])
                    ),
                )
            )
        cards_html = "\n".join(parts)

    return PAGE_TMPL.format(
        price_min=f"{CRITERIA['price_min']:,.0f}".replace(",", "."),
        price_max=f"{CRITERIA['price_max']:,.0f}".replace(",", "."),
        area_priority=f"{CRITERIA['area_priority_min']:,.0f}".replace(",", "."),
        count=len(visible_listings),
        now=datetime.now(TZ_BR).strftime("%d/%m %H:%M"),
        cards=cards_html,
        bairro_options=bairro_options,
        excluded_chips=excluded_chips,
        tab_all_active=" active" if view == "all" else "",
        tab_fav_active=" active" if view == "favorites" else "",
        tab_clicked_active=" active" if view == "clicked" else "",
        tab_visits_active=" active" if view == "visits" else "",
    )


@app.route("/")
def report():
    return Response(render_page("all"), mimetype="text/html")


@app.route("/favoritos")
def favoritos():
    return Response(render_page("favorites"), mimetype="text/html")


@app.route("/abertos")
def abertos():
    return Response(render_page("clicked"), mimetype="text/html")


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


@app.route("/visitas")
def visitas():
    return Response(render_page("visits"), mimetype="text/html")


@app.route("/api/visit", methods=["POST"])
def api_visit():
    data = request.get_json(silent=True) or {}
    uid = data.get("uid", "")
    visit = bool(data.get("visit"))
    if not uid:
        return jsonify({"ok": False, "error": "uid obrigatório"}), 400
    ok = set_visit(DB_PATH, uid, visit)
    return jsonify({"ok": ok})


@app.route("/api/click", methods=["POST"])
def api_click():
    data = request.get_json(silent=True) or {}
    uid = data.get("uid", "")
    if not uid:
        return jsonify({"ok": False, "error": "uid obrigatório"}), 400
    ok = mark_clicked(DB_PATH, uid)
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
