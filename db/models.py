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
        isha TEXT
    )
    """)
    conn.commit()
    # Добавляем столбец shurooq, если его нет (для существующих таблиц)
    try:
        conn.execute("ALTER TABLE prayer_times ADD COLUMN shurooq TEXT")
        conn.commit()
    except Exception:
        # Столбец уже существует, игнорируем ошибку
        pass