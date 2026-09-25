import logging
import time

from config import SITES, CRITERIA, DB_PATH
from scraper.base import fetch_html, Listing
from scraper.sites import get_parser
from scraper.storage import init_db, check_and_record, get_excluded_bairros, set_last_new_uids
from scraper.notifier import notify_run_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("scraper")


def passes_price_filter(listing: Listing) -> bool:
    if listing.price is None:
        return False
    return CRITERIA["price_min"] <= listing.price <= CRITERIA["price_max"]


def fetch_site_listings(site: dict) -> list[Listing]:
    """Baixa e parseia um site. Com "paginate" na config, segue ?<param>=2,3,...
    até max_pages ou até uma página não trazer nenhum anúncio novo (alguns sites
    repetem a última página quando o número passa do fim)."""
    name, url, platform = site["name"], site["url"], site["platform"]
    parser = get_parser(platform)
    paginate = site.get("paginate")
    max_pages = paginate["max_pages"] if paginate else 1

    listings: list[Listing] = []
    seen = set()
    for page in range(1, max_pages + 1):
        page_url = url
        if page > 1:
            sep = "&" if "?" in url else "?"
            page_url = f"{url}{sep}{paginate['param']}={page}"
        html = fetch_html(page_url)
        if not html:
            logger.warning("HTML vazio para %s (página %d)", name, page)
            break
        fresh = [l for l in parser(html, url, name) if l.uid not in seen]
        if not fresh:
            break
        seen.update(l.uid for l in fresh)
        listings.extend(fresh)
    return listings


def run_once(notify_always: bool = False):
    init_db(DB_PATH)
    excluded_bairros = {b.lower() for b in get_excluded_bairros(DB_PATH)}
    total_new = 0
    total_price_changed = 0
    new_uids = []

    for site in SITES:
        name, url = site["name"], site["url"]
        logger.info("Verificando: %s (%s)", name, url)
        try:
            listings = fetch_site_listings(site)
            logger.info("  %d anúncios extraídos", len(listings))

            for listing in listings:
                if not passes_price_filter(listing):
                    continue
                if listing.location and listing.location.lower() in excluded_bairros:
                    continue

                result = check_and_record(DB_PATH, listing)

                if result["is_new"]:
                    total_new += 1
                    new_uids.append(listing.uid)
                    logger.info("  NOVO: %s - R$ %.0f", listing.title, listing.price)
                elif result["price_changed"]:
                    total_price_changed += 1
                    logger.info(
                        "  PREÇO MUDOU: %s - R$ %.0f -> R$ %.0f",
                        listing.title, result["old_price"], listing.price,
                    )

        except Exception as e:
            logger.exception("Erro ao processar %s: %s", name, e)

        time.sleep(2)  # respiro entre sites

    set_last_new_uids(DB_PATH, new_uids)

    if total_new or total_price_changed or notify_always:
        notify_run_summary(total_new, total_price_changed, forced=notify_always)

    logger.info(
        "Execução concluída. %d novos anúncios, %d mudanças de preço.",
        total_new, total_price_changed,
    )


if __name__ == "__main__":
    run_once()
