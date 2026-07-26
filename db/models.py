import logging

logger = logging.getLogger(__name__)

USER_LOCATION_COLUMNS: dict[str, str] = {
    "latitude": "REAL",
    "longitude": "REAL",
    "timezone": "TEXT",
    "calculation_method": "TEXT DEFAULT 'auto'",
    "use_hanafi": "INTEGER DEFAULT 1",
    "madhab_manual": "INTEGER DEFAULT 0",
    "fajr_angle": "REAL DEFAULT 16.0",
    "isha_angle": "REAL DEFAULT 15.0",
}


def _ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    """Добавляет отсутствующие колонки в существующую таблицу."""
    existing = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, ddl_type in columns.items():
        if name in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}")
            conn.commit()
            logger.info("✅ Добавлена колонка %s.%s", table, name)
        except Exception as exc:
            logger.warning("⚠️ Не удалось добавить колонку %s.%s: %s", table, name, exc)


def create_table(conn) -> None:
    """Создаёт/мигрирует таблицы prayer_times, users, user_prayer_times."""
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

    existing_cols = [row[1] for row in conn.execute("PRAGMA table_info(prayer_times)").fetchall()]

    if "shurooq" not in existing_cols:
        try:
            conn.execute("ALTER TABLE prayer_times ADD COLUMN shurooq TEXT")
            conn.commit()
            logger.info("✅ Добавлена колонка shurooq")
        except Exception as e:
            logger.warning("⚠️ Не удалось добавить колонку shurooq: %s", e)

    if "month_updated" not in existing_cols:
        try:
            conn.execute("ALTER TABLE prayer_times ADD COLUMN month_updated INTEGER DEFAULT 0")
            conn.commit()
            logger.info("✅ Добавлена колонка month_updated")
        except Exception as e:
            logger.warning("⚠️ Не удалось добавить колонку month_updated: %s", e)

    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_prayer_times_date ON prayer_times(date)")
        conn.commit()
    except Exception:
        pass

    conn.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT UNIQUE,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        subscribed INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        latitude REAL,
        longitude REAL,
        timezone TEXT,
        calculation_method TEXT DEFAULT 'auto',
        use_hanafi INTEGER DEFAULT 1,
        madhab_manual INTEGER DEFAULT 0,
        fajr_angle REAL DEFAULT 16.0,
        isha_angle REAL DEFAULT 15.0
    )
    """)
    conn.commit()
    _ensure_columns(conn, "users", USER_LOCATION_COLUMNS)

    conn.execute("""
    CREATE TABLE IF NOT EXISTS user_prayer_times (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        date TEXT NOT NULL,
        fajr TEXT,
        shurooq TEXT,
        dhuhr TEXT,
        asr TEXT,
        maghrib TEXT,
        isha TEXT,
        UNIQUE(chat_id, date)
    )
    """)
    conn.commit()

    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_prayer_times_chat_date "
            "ON user_prayer_times(chat_id, date)"
        )
        conn.commit()
    except Exception:
        pass
