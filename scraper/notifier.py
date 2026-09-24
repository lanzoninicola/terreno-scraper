import logging
import requests

from config import WHATSAPP_API_URL, WHATSAPP_API_KEY, WHATSAPP_TARGET_PHONES, REPORT_URL

logger = logging.getLogger("scraper")


def send_whatsapp(message: str) -> bool:
    if not WHATSAPP_API_KEY or not WHATSAPP_TARGET_PHONES:
        logger.warning(
            "AMODOMIO_API_KEY ou TARGET_PHONE não configurados — mensagem não enviada:\n%s",
            message,
        )
        return False

    all_ok = True
    for phone in WHATSAPP_TARGET_PHONES:
        try:
            resp = requests.post(
                WHATSAPP_API_URL,
                headers={
                    "Content-Type": "application/json",
                    "x-api-key": WHATSAPP_API_KEY,
                },
                json={"phone": phone, "message": message},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.error("Falha ao enviar WhatsApp para %s: %s", phone, e)
            all_ok = False
    return all_ok


def notify_run_summary(new_count: int, changed_count: int) -> bool:
    """Uma única mensagem por execução, só quando há algo novo, com o link fixo do relatório."""
    if new_count == 0 and changed_count == 0:
        return False

    parts = []
    if new_count:
        parts.append(f"{new_count} novo(s)")
    if changed_count:
        parts.append(f"{changed_count} com preço alterado")

    msg = f"🏗️ Terrenos: {' e '.join(parts)}\n{REPORT_URL}"
    return send_whatsapp(msg)
