from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
import logging

logger = logging.getLogger(__name__)


def insert_prayer(conn, data, month_updated=None):
    """Вставляет или обновляет запись о времени намаза (legacy global table)."""
    try:
        cursor = conn.execute("SELECT id FROM prayer_times WHERE date=?", (data[0],))
        existing = cursor.fetchone()

        if existing:
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
    """Получает время намазов по дате (legacy)."""
    cursor = conn.execute("SELECT * FROM prayer_times WHERE date=?", (date,))
    return cursor.fetchone()


def get_all_prayers(conn):
    """Получает все записи из таблицы prayer_times."""
    cursor = conn.execute("SELECT * FROM prayer_times ORDER BY date")
    return cursor.fetchall()


def get_by_month(conn, year: int, month: int):
    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{month+1:02d}-01"

    cursor = conn.execute("""
        SELECT date, fajr, shurooq, dhuhr, asr, maghrib, isha
        FROM prayer_times
        WHERE date >= ? AND date < ?
        ORDER BY date
    """, (start_date, end_date))
    return cursor.fetchall()


def get_date_range(conn):
    """Получает минимальную и максимальную дату в таблице prayer_times."""
    cursor = conn.execute("SELECT MIN(date), MAX(date) FROM prayer_times")
    return cursor.fetchone()


def is_data_actual(conn, year: int, month: int) -> bool:
    """Проверяет наличие данных в БД для указанного месяца (legacy)."""
    cursor = conn.execute(
        "SELECT COUNT(*) FROM prayer_times WHERE date >= ? AND date < ?",
        (f"{year}-{month:02d}-01",
         f"{year}-{month+1:02d}-01" if month < 12 else f"{year+1}-01-01")
    )
    count = cursor.fetchone()[0]
    return count > 0


def get_prayer_by_date_and_name(conn, date: str, prayer_name: str) -> Optional[str]:
    """Получает время конкретного намаза по дате (legacy global table)."""
    prayer_column_map = {
        "Фаджр": "fajr",
        "Шурук": "shurooq",
        "Зухр": "dhuhr",
        "Аср": "asr",
        "Магриб": "maghrib",
        "Иша": "isha",
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


def insert_or_update_user(
    conn,
    chat_id,
    username=None,
    first_name=None,
    last_name=None,
) -> bool:
    """Добавляет или обновляет пользователя в БД (UPSERT базовых полей)."""
    try:
        conn.execute("""
            INSERT INTO users (chat_id, username, first_name, last_name, subscribed)
            VALUES (?, ?, ?, ?, 1)
            ON CONFLICT(chat_id) DO UPDATE SET
                username=excluded.username,
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                subscribed=1,
                updated_at=CURRENT_TIMESTAMP
        """, (str(chat_id), username, first_name, last_name))
        conn.commit()
        return True
    except Exception as e:
        logger.error("❌ Ошибка при сохранении пользователя %s: %s", chat_id, e)
        return False


def update_user_location(
    conn,
    chat_id: str | int,
    latitude: float,
    longitude: float,
    timezone: str,
    calculation_method: str,
    madhab: str,
    fajr_angle: float,
    isha_angle: float,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    preserve_madhab: bool = False,
) -> bool:
    """Сохраняет геоданные и параметры расчёта пользователя."""
    from services.madhab import madhab_uses_hanafi_asr, normalize_madhab

    try:
        chat_id_str = str(chat_id)
        madhab_code = normalize_madhab(madhab)
        use_hanafi = 1 if madhab_uses_hanafi_asr(madhab_code) else 0

        if preserve_madhab:
            conn.execute("""
                INSERT INTO users (
                    chat_id, username, first_name, last_name, subscribed,
                    latitude, longitude, timezone, calculation_method,
                    use_hanafi, madhab, fajr_angle, isha_angle
                )
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    username=COALESCE(excluded.username, users.username),
                    first_name=COALESCE(excluded.first_name, users.first_name),
                    last_name=COALESCE(excluded.last_name, users.last_name),
                    subscribed=1,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude,
                    timezone=excluded.timezone,
                    calculation_method=excluded.calculation_method,
                    fajr_angle=excluded.fajr_angle,
                    isha_angle=excluded.isha_angle,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                chat_id_str,
                username,
                first_name,
                last_name,
                latitude,
                longitude,
                timezone,
                calculation_method,
                use_hanafi,
                madhab_code,
                fajr_angle,
                isha_angle,
            ))
        else:
            conn.execute("""
                INSERT INTO users (
                    chat_id, username, first_name, last_name, subscribed,
                    latitude, longitude, timezone, calculation_method,
                    use_hanafi, madhab, fajr_angle, isha_angle
                )
                VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    username=COALESCE(excluded.username, users.username),
                    first_name=COALESCE(excluded.first_name, users.first_name),
                    last_name=COALESCE(excluded.last_name, users.last_name),
                    subscribed=1,
                    latitude=excluded.latitude,
                    longitude=excluded.longitude,
                    timezone=excluded.timezone,
                    calculation_method=excluded.calculation_method,
                    use_hanafi=excluded.use_hanafi,
                    madhab=excluded.madhab,
                    fajr_angle=excluded.fajr_angle,
                    isha_angle=excluded.isha_angle,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                chat_id_str,
                username,
                first_name,
                last_name,
                latitude,
                longitude,
                timezone,
                calculation_method,
                use_hanafi,
                madhab_code,
                fajr_angle,
                isha_angle,
            ))
        conn.commit()
        return True
    except Exception as e:
        logger.error("❌ Ошибка при сохранении геоданных пользователя %s: %s", chat_id, e)
        return False


def update_user_madhab(conn, chat_id: str | int, madhab: str) -> bool:
    """Обновляет мазхаб Аср и помечает выбор как ручной."""
    from services.madhab import madhab_uses_hanafi_asr, normalize_madhab

    try:
        madhab_code = normalize_madhab(madhab)
        use_hanafi = 1 if madhab_uses_hanafi_asr(madhab_code) else 0
        cursor = conn.execute("""
            UPDATE users
            SET madhab=?,
                use_hanafi=?,
                madhab_manual=1,
                updated_at=CURRENT_TIMESTAMP
            WHERE chat_id=?
        """, (madhab_code, use_hanafi, str(chat_id)))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        logger.error("❌ Ошибка при обновлении мазхаба пользователя %s: %s", chat_id, e)
        return False


def get_all_users(conn):
    """Получает всех подписанных пользователей."""
    cursor = conn.execute("SELECT * FROM users WHERE subscribed=1 ORDER BY created_at")
    return cursor.fetchall()


def get_users_with_location(conn):
    """Получает подписанных пользователей с заданными координатами."""
    cursor = conn.execute("""
        SELECT * FROM users
        WHERE subscribed=1
          AND latitude IS NOT NULL
          AND longitude IS NOT NULL
          AND timezone IS NOT NULL
        ORDER BY created_at
    """)
    return cursor.fetchall()


def get_user_by_chat_id(conn, chat_id):
    """Получает пользователя по chat_id."""
    cursor = conn.execute("SELECT * FROM users WHERE chat_id=?", (str(chat_id),))
    return cursor.fetchone()


def user_has_location(user: Any) -> bool:
    """Проверяет, задана ли у пользователя локация для расчёта."""
    if user is None:
        return False
    return (
        user["latitude"] is not None
        and user["longitude"] is not None
        and bool(user["timezone"])
    )


def update_user_subscription(conn, chat_id, subscribed) -> bool:
    """Обновляет статус подписки пользователя."""
    try:
        conn.execute(
            "UPDATE users SET subscribed=? WHERE chat_id=?",
            (subscribed, str(chat_id)),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error("❌ Ошибка при обновлении подписки пользователя %s: %s", chat_id, e)
        return False


def delete_user(conn, chat_id) -> bool:
    """Удаляет пользователя и его персональное расписание."""
    try:
        chat_id_str = str(chat_id)
        conn.execute("DELETE FROM user_prayer_times WHERE chat_id=?", (chat_id_str,))
        conn.execute("DELETE FROM users WHERE chat_id=?", (chat_id_str,))
        conn.commit()
        return True
    except Exception as e:
        logger.error("❌ Ошибка при удалении пользователя %s: %s", chat_id, e)
        return False


def upsert_user_prayer(conn, chat_id: str | int, data: tuple) -> bool:
    """
    UPSERT одной записи персонального расписания.

    data: (date, fajr, shurooq, dhuhr, asr, maghrib, isha)
    """
    try:
        conn.execute("""
            INSERT INTO user_prayer_times
                (chat_id, date, fajr, shurooq, dhuhr, asr, maghrib, isha)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, date) DO UPDATE SET
                fajr=excluded.fajr,
                shurooq=excluded.shurooq,
                dhuhr=excluded.dhuhr,
                asr=excluded.asr,
                maghrib=excluded.maghrib,
                isha=excluded.isha
        """, (str(chat_id), *data))
        return True
    except Exception as e:
        logger.error(
            "❌ Ошибка UPSERT user_prayer_times chat_id=%s date=%s: %s",
            chat_id, data[0], e,
        )
        return False


def get_user_prayers_by_date(conn, chat_id: str | int, date: str):
    """Возвращает персональное расписание пользователя на дату."""
    cursor = conn.execute("""
        SELECT date, fajr, shurooq, dhuhr, asr, maghrib, isha
        FROM user_prayer_times
        WHERE chat_id=? AND date=?
    """, (str(chat_id), date))
    return cursor.fetchone()


def get_user_prayers_by_month(conn, chat_id: str | int, year: int, month: int):
    """Возвращает персональное расписание пользователя на месяц."""
    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{month+1:02d}-01"

    cursor = conn.execute("""
        SELECT date, fajr, shurooq, dhuhr, asr, maghrib, isha
        FROM user_prayer_times
        WHERE chat_id=? AND date >= ? AND date < ?
        ORDER BY date
    """, (str(chat_id), start_date, end_date))
    return cursor.fetchall()


def get_user_prayer_by_date_and_name(
    conn,
    chat_id: str | int,
    date: str,
    prayer_name: str,
) -> Optional[str]:
    """Получает время конкретного намаза пользователя."""
    prayer_column_map = {
        "Фаджр": "fajr",
        "Шурук": "shurooq",
        "Зухр": "dhuhr",
        "Аср": "asr",
        "Магриб": "maghrib",
        "Иша": "isha",
    }
    col = prayer_column_map.get(prayer_name)
    if not col:
        return None

    cursor = conn.execute(
        f"SELECT {col} FROM user_prayer_times WHERE chat_id=? AND date=?",
        (str(chat_id), date),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def is_user_month_actual(conn, chat_id: str | int, year: int, month: int) -> bool:
    """Проверяет, есть ли у пользователя данные на месяц."""
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year+1}-01-01" if month == 12 else f"{year}-{month+1:02d}-01"
    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM user_prayer_times
        WHERE chat_id=? AND date >= ? AND date < ?
        """,
        (str(chat_id), start_date, end_date),
    )
    return cursor.fetchone()[0] > 0
