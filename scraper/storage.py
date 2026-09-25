import sqlite3
import os
import json
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
            location TEXT,
            description TEXT,
            status TEXT,
            first_seen REAL,
            last_seen REAL,
            last_price REAL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    # migração leve: adiciona colunas novas em bancos criados antes desta versão
    for col, coltype in [
        ("location", "TEXT"), ("description", "TEXT"), ("status", "TEXT"),
        ("favorite", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {coltype}")
        except sqlite3.OperationalError:
            pass  # coluna já existe
    conn.commit()
    conn.close()


@contextmanager
def _connect(path: str):
    conn = sqlite3.connect(path)
    try:
        yield conn
    finally:
        conn.close()


def get_all_listings(path: str, limit: int = 300, favorites_only: bool = False) -> list[dict]:
    """Devolve os anúncios salvos, mais novos primeiro (por first_seen)."""
    with _connect(path) as conn:
        conn.row_factory = sqlite3.Row
        where = "WHERE favorite = 1" if favorites_only else ""
        rows = conn.execute(
            f"""SELECT uid, site, title, url, price, area, location, description,
                       status, favorite, first_seen, last_seen, last_price
                FROM listings {where} ORDER BY first_seen DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_last_new_uids(path: str) -> list[str]:
    """uids que entraram como 'novo' na última execução do scraper (pra marcar o badge NOVO)."""
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'last_new_uids'"
        ).fetchone()
        if not row or not row[0]:
            return []
        return json.loads(row[0])


def set_last_new_uids(path: str, uids: list[str]):
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('last_new_uids', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(uids),),
        )
        conn.commit()


def set_favorite(path: str, uid: str, favorite: bool) -> bool:
    with _connect(path) as conn:
        cur = conn.execute(
            "UPDATE listings SET favorite = ? WHERE uid = ?", (1 if favorite else 0, uid)
        )
        conn.commit()
        return cur.rowcount > 0


def set_status(path: str, uid: str, status: str) -> bool:
    """status: '' (ativo/novo), 'seen' (já visto) ou 'dismissed' (não interessa)."""
    with _connect(path) as conn:
        cur = conn.execute(
            "UPDATE listings SET status = ? WHERE uid = ?", (status, uid)
        )
        conn.commit()
        return cur.rowcount > 0


def get_excluded_bairros(path: str) -> list[str]:
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'excluded_bairros'"
        ).fetchone()
        if not row or not row[0]:
            return []
        return json.loads(row[0])


def set_bairro_excluded(path: str, bairro: str, excluded: bool) -> list[str]:
    with _connect(path) as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'excluded_bairros'"
        ).fetchone()
        current = json.loads(row[0]) if row and row[0] else []
        current_set = {b.lower() for b in current}

        if excluded and bairro.lower() not in current_set:
            current.append(bairro)
        elif not excluded:
            current = [b for b in current if b.lower() != bairro.lower()]

        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('excluded_bairros', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (json.dumps(current),),
        )
        conn.commit()
        return current


def try_start_run(path: str, ttl_seconds: int = 1800) -> bool:
    """Lock simples pra evitar duas buscas manuais rodando ao mesmo tempo."""
    now = time.time()
    with _connect(path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'run_lock'").fetchone()
        if row and row[0]:
            try:
                started = float(row[0])
            except ValueError:
                started = 0
            if now - started < ttl_seconds:
                return False
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('run_lock', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(now),),
        )
        conn.commit()
        return True


def finish_run(path: str):
    with _connect(path) as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('run_lock', '0') "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value"
        )
        conn.commit()


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
                   location, description, first_seen, last_seen, last_price)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    listing.uid, listing.site, listing.title, listing.url,
                    listing.price, listing.area, listing.location,
                    listing.description, now, now, listing.price,
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
            """UPDATE listings SET last_seen = ?, last_price = ?, area = ?,
               location = ?, description = ? WHERE uid = ?""",
            (now, listing.price, listing.area, listing.location,
             listing.description, listing.uid),
        )
        conn.commit()
        return {"is_new": False, "price_changed": price_changed, "old_price": old_price}
