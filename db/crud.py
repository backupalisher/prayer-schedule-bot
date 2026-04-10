from datetime import datetime


def insert_prayer(conn, data):
    """Вставляет или обновляет запись о времени намаза"""
    try:
        # Проверяем, существует ли уже запись
        cursor = conn.execute("SELECT id FROM prayer_times WHERE date=?", (data[0],))
        existing = cursor.fetchone()

        if existing:
            # Обновляем существующую запись
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
            conn.execute("""
                         INSERT INTO prayer_times (date, fajr, shurooq, dhuhr, asr, maghrib, isha)
                         VALUES (?, ?, ?, ?, ?, ?, ?)
                         """, data)

        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Ошибка вставки/обновления для {data[0]}: {e}")
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


# Функции для работы с пользователями
def insert_or_update_user(conn, chat_id, username=None, first_name=None, last_name=None):
    """Добавляет или обновляет пользователя в БД"""
    try:
        # Проверяем, существует ли уже пользователь
        cursor = conn.execute("SELECT id FROM users WHERE chat_id=?", (str(chat_id),))
        existing = cursor.fetchone()

        if existing:
            # Обновляем существующего пользователя
            conn.execute("""
                         UPDATE users 
                         SET username=?, first_name=?, last_name=?, updated_at=CURRENT_TIMESTAMP
                         WHERE chat_id=?
                         """, (username, first_name, last_name, str(chat_id)))
        else:
            # Вставляем нового пользователя
            conn.execute("""
                         INSERT INTO users (chat_id, username, first_name, last_name)
                         VALUES (?, ?, ?, ?)
                         """, (str(chat_id), username, first_name, last_name))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Ошибка при сохранении пользователя {chat_id}: {e}")
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
        print(f"❌ Ошибка при обновлении подписки пользователя {chat_id}: {e}")
        return False


def delete_user(conn, chat_id):
    """Удаляет пользователя из БД"""
    try:
        conn.execute("DELETE FROM users WHERE chat_id=?", (str(chat_id),))
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Ошибка при удалении пользователя {chat_id}: {e}")
        return False