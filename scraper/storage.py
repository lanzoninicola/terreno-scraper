import sqlite3
import os
import time
from contextlib import contextmanager

from .base import Listing


def init_db(path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            uid TEXT PRIMARY KEY,
            site TEXT,
            title TEXT,
            url TEXT,
            price REAL,
            area REAL,
            first_seen REAL,
            last_seen REAL,
            last_price REAL
        )
        """
    )
    conn.commit()
    conn.close()


@contextmanager
def _connect(path: str):
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def check_and_record(path: str, listing: Listing) -> dict:
    """
    Registra o listing e devolve o que mudou:
      {"is_new": bool, "price_changed": bool, "old_price": float|None}
    """
    now = time.time()
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT last_price FROM listings WHERE uid = ?", (listing.uid,)
        ).fetchone()

        if row is None:
            conn.execute(
                """INSERT INTO listings (uid, site, title, url, price, area,
                   first_seen, last_seen, last_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    listing.uid, listing.site, listing.title, listing.url,
                    listing.price, listing.area, now, now, listing.price,
                ),
            )
            conn.commit()
            return {"is_new": True, "price_changed": False, "old_price": None}

        old_price = row[0]
        price_changed = (
            listing.price is not None
            and old_price is not None
            and abs(listing.price - old_price) > 0.01
        )
        conn.execute(
            """UPDATE listings SET last_seen = ?, last_price = ?, area = ?
               WHERE uid = ?""",
            (now, listing.price, listing.area, listing.uid),
        )
        conn.commit()
        return {"is_new": False, "price_changed": price_changed, "old_price": old_price}
