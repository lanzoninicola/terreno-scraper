import logging
import time

from config import SCRAPE_INTERVAL_MINUTES
from main import run_once

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("scheduler")

if __name__ == "__main__":
    logger.info(
        "Scheduler iniciado — rodando a cada %d minutos", SCRAPE_INTERVAL_MINUTES
    )
    while True:
        try:
            run_once()
        except Exception:
            logger.exception("Erro na execução do scraper")
        logger.info("Aguardando %d minutos até a próxima checagem...", SCRAPE_INTERVAL_MINUTES)
        time.sleep(SCRAPE_INTERVAL_MINUTES * 60)
