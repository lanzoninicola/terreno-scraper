import logging
import requests

from config import WHATSAPP_API_URL, WHATSAPP_API_KEY, WHATSAPP_TARGET_PHONE

logger = logging.getLogger("scraper")


def send_whatsapp(message: str) -> bool:
    if not WHATSAPP_API_KEY or not WHATSAPP_TARGET_PHONE:
        logger.warning(
            "AMODOMIO_API_KEY ou TARGET_PHONE não configurados — mensagem não enviada:\n%s",
            message,
        )
        return False

    try:
        resp = requests.post(
            WHATSAPP_API_URL,
            headers={
                "Content-Type": "application/json",
                "x-api-key": WHATSAPP_API_KEY,
            },
            json={"phone": WHATSAPP_TARGET_PHONE, "message": message},
            timeout=15,
        )
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        logger.error("Falha ao enviar WhatsApp: %s", e)
        return False


def format_listing_message(listing, is_priority: bool, price_changed: bool = False, old_price=None) -> str:
    star = "⭐ " if is_priority else ""
    lines = [f"{star}*Novo terreno* — {listing.site}", listing.title]
    if listing.price:
        lines.append(f"💰 R$ {listing.price:,.0f}".replace(",", "."))
    if listing.area:
        lines.append(f"📐 {listing.area:,.0f} m²".replace(",", "."))
    if price_changed and old_price:
        lines.append(f"(preço mudou de R$ {old_price:,.0f})".replace(",", "."))
    lines.append(listing.url)
    return "\n".join(lines)
