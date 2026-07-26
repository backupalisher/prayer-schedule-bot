import sqlite3
import os

DB_PATH = "prayers.db"


def get_connection() -> sqlite3.Connection:
    """Возвращает соединение с БД (доступ к колонкам по имени и индексу)."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Инициализирует базу данных."""
    conn = get_connection()
    try:
        from db.models import create_table
        create_table(conn)
    finally:
        conn.close()
