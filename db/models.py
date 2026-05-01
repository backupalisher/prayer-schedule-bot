import logging

logger = logging.getLogger(__name__)


def create_table(conn):
    """Создает таблицу prayer_times если её нет"""
    conn.execute("""
    CREATE TABLE IF NOT EXISTS prayer_times (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE,
        fajr TEXT,
        shurooq TEXT,
        dhuhr TEXT,
        asr TEXT,
        maghrib TEXT,
        isha TEXT,
        month_updated INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    # Добавляем столбцы для обратной совместимости с существующими таблицами
    # Проверяем, какие колонки уже есть
    existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(prayer_times)").fetchall()]
    
    if 'shurooq' not in existing_cols:
        try:
            conn.execute("ALTER TABLE prayer_times ADD COLUMN shurooq TEXT")
            conn.commit()
            logger.info("✅ Добавлена колонка shurooq")
        except Exception as e:
            logger.warning("⚠️ Не удалось добавить колонку shurooq: %s", e)
    
    if 'month_updated' not in existing_cols:
        try:
            conn.execute("ALTER TABLE prayer_times ADD COLUMN month_updated INTEGER DEFAULT 0")
            conn.commit()
            logger.info("✅ Добавлена колонка month_updated")
        except Exception as e:
            logger.warning("⚠️ Не удалось добавить колонку month_updated: %s", e)
    
    # Создаем индекс для быстрого поиска по дате
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prayer_times_date ON prayer_times(date)")
        conn.commit()
    except Exception:
        pass
    
    # Создаем таблицу пользователей для хранения chat_id
    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT UNIQUE,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        subscribed INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()