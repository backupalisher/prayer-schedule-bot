from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def insert_prayer(conn, data, month_updated=None):
    """Вставляет или обновляет запись о времени намаза"""
    try:
        # Проверяем, существует ли уже запись
        cursor = conn.execute("SELECT id FROM prayer_times WHERE date=?", (data[0],))
        existing = cursor.fetchone()

        if existing:
            # Обновляем существующую запись
            if month_updated is not None:
                conn.execute("""
                             UPDATE prayer_times
                             SET fajr=?,
                                 shurooq=?,
                                 dhuhr=?,
                                 asr=?,
                                 maghrib=?,
                                 isha=?,
                                 month_updated=?
                             WHERE date=?
                             """, (data[1], data[2], data[3], data[4], data[5], data[6], month_updated, data[0]))
            else:
                conn.execute("""
                             UPDATE prayer_times
                             SET fajr=?,
                                 shurooq=?,
                                 dhuhr=?,
                                 asr=?,
                                 maghrib=?,
                                 isha=?
                             WHERE date=?
                             """, (data[1], data[2], data[3], data[4], data[5], data[6], data[0]))
        else:
            # Вставляем новую запись
            if month_updated is not None:
                conn.execute("""
                             INSERT INTO prayer_times (date, fajr, shurooq, dhuhr, asr, maghrib, isha, month_updated)
                             VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                             """, (*data, month_updated))
            else:
                conn.execute("""
                             INSERT INTO prayer_times (date, fajr, shurooq, dhuhr, asr, maghrib, isha)
                             VALUES (?, ?, ?, ?, ?, ?, ?)
                             """, data)

        conn.commit()
        return True
    except Exception as e:
        logger.error("❌ Ошибка вставки/обновления для %s: %s", data[0], e)
        return False


def get_by_date(conn, date):
    """Получает время намазов по дате"""
    cursor = conn.execute("SELECT * FROM prayer_times WHERE date=?", (date,))
    return cursor.fetchone()


def get_all_prayers(conn):
    """Получает все записи из таблицы prayer_times"""
    cursor = conn.execute("SELECT * FROM prayer_times ORDER BY date")
    return cursor.fetchall()


def get_by_month(conn, year: int, month: int):
    cursor = conn.cursor()

    start_date = f"{year}-{month:02d}-01"

    # следующий месяц
    if month == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{month+1:02d}-01"

    cursor.execute("""
        SELECT date, fajr, shurooq, dhuhr, asr, maghrib, isha
        FROM prayer_times
        WHERE date >= ? AND date < ?
        ORDER BY date
    """, (start_date, end_date))

    return cursor.fetchall()


def get_date_range(conn):
    """Получает минимальную и максимальную дату в таблице prayer_times"""
    cursor = conn.execute("SELECT MIN(date), MAX(date) FROM prayer_times")
    return cursor.fetchone()


def is_data_actual(conn, year: int, month: int) -> bool:
    """
    Проверяет, актуальны ли данные в БД для указанного месяца.
    Проверяет по month_updated или по наличию дат в диапазоне.
    """
    cursor = conn.execute(
        "SELECT COUNT(*) FROM prayer_times WHERE date >= ? AND date < ?",
        (f"{year}-{month:02d}-01",
         f"{year}-{month+1:02d}-01" if month < 12 else f"{year+1}-01-01")
    )
    count = cursor.fetchone()[0]
    return count > 0


def get_prayer_by_date_and_name(conn, date: str, prayer_name: str) -> str:
    """
    Получает время конкретного намаза по дате и названию.
    Возвращает строку времени в формате ЧЧ:ММ или None.
    """
    prayer_column_map = {
        'Фаджр': 'fajr',
        'Шурук': 'shurooq',
        'Зухр': 'dhuhr',
        'Аср': 'asr',
        'Магриб': 'maghrib',
        'Иша': 'isha',
    }
    col = prayer_column_map.get(prayer_name)
    if not col:
        return None
    
    cursor = conn.execute(
        f"SELECT {col} FROM prayer_times WHERE date=?",
        (date,)
    )
    row = cursor.fetchone()
    return row[0] if row else None


# Функции для работы с пользователями
def insert_or_update_user(conn, chat_id, username=None, first_name=None, last_name=None):
    """Добавляет или обновляет пользователя в БД (UPSERT)"""
    try:
        conn.execute("""
            INSERT INTO users (chat_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                updated_at=CURRENT_TIMESTAMP
        """, (str(chat_id), username, first_name, last_name))
        
        conn.commit()
        return True
    except Exception as e:
        logger.error("❌ Ошибка при сохранении пользователя %s: %s", chat_id, e)
        return False


def get_all_users(conn):
    """Получает всех пользователей из БД"""
    cursor = conn.execute("SELECT * FROM users WHERE subscribed=1 ORDER BY created_at")
    return cursor.fetchall()


def get_user_by_chat_id(conn, chat_id):
    """Получает пользователя по chat_id"""
    cursor = conn.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),))
    return cursor.fetchone()


def update_user_subscription(conn, chat_id, subscribed):
    """Обновляет статус подписки пользователя"""
    try:
        conn.execute("UPDATE users SET subscribed=? WHERE chat_id=?", (subscribed, str(chat_id)))
        conn.commit()
        return True
    except Exception as e:
        logger.error("❌ Ошибка при обновлении подписки пользователя %s: %s", chat_id, e)
        return False


def delete_user(conn, chat_id):
    """Удаляет пользователя из БД"""
    try:
        conn.execute("DELETE FROM users WHERE chat_id=?", (str(chat_id),))
        conn.commit()
        return True
    except Exception as e:
        logger.error("❌ Ошибка при удалении пользователя %s: %s", chat_id, e)
        return False