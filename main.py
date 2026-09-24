import logging
import time

from config import SITES, CRITERIA, DB_PATH
from scraper.base import fetch_html, Listing
from scraper.sites import get_parser
from scraper.storage import init_db, check_and_record
from scraper.notifier import send_whatsapp, format_listing_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("scraper")


def passes_price_filter(listing: Listing) -> bool:
    if listing.price is None:
        return False
    return CRITERIA["price_min"] <= listing.price <= CRITERIA["price_max"]


def is_priority(listing: Listing) -> bool:
    return listing.area is not None and listing.area >= CRITERIA["area_priority_min"]


def run_once():
    init_db(DB_PATH)
    total_new = 0
    total_price_changed = 0

    for site in SITES:
        name, url, platform = site["name"], site["url"], site["platform"]
        logger.info("Verificando: %s (%s)", name, url)
        try:
            html = fetch_html(url)
            if not html:
                logger.warning("HTML vazio para %s — pulando", name)
                continue

            parser = get_parser(platform)
            listings = parser(html, url, name)
            logger.info("  %d anúncios extraídos", len(listings))

            for listing in listings:
                if not passes_price_filter(listing):
                    continue

                result = check_and_record(DB_PATH, listing)
                priority = is_priority(listing)

                if result["is_new"]:
                    total_new += 1
                    msg = format_listing_message(listing, priority)
                    send_whatsapp(msg)
                    logger.info("  NOVO: %s - R$ %.0f", listing.title, listing.price)
                elif result["price_changed"]:
                    total_price_changed += 1
                    msg = format_listing_message(
                        listing, priority, price_changed=True, old_price=result["old_price"]
                    )
                    send_whatsapp(msg)
                    logger.info(
                        "  PREÇO MUDOU: %s - R$ %.0f -> R$ %.0f",
                        listing.title, result["old_price"], listing.price,
                    )

        except Exception as e:
            logger.exception("Erro ao processar %s: %s", name, e)

        time.sleep(2)  # respiro entre sites

    logger.info(
        "Execução concluída. %d novos anúncios, %d mudanças de preço.",
        total_new, total_price_changed,
    )


if __name__ == "__main__":
    run_once()
