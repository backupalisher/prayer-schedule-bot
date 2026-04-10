import sqlite3
import os

DB_PATH = "prayers.db"

def get_connection():
    """Возвращает соединение с БД"""
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    """Инициализирует базу данных"""
    conn = get_connection()
    try:
        from db.models import create_table
        create_table(conn)
    finally:
        conn.close()