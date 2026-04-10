from datetime import datetime
from db.database import get_connection
from db.crud import get_by_date

# Константы для индексов столбцов в таблице prayer_times
COLUMN_INDEXES = {
    'id': 0,
    'date': 1,
    'fajr': 2,
    'shurooq': 3,
    'dhuhr': 4,
    'asr': 5,
    'maghrib': 6,
    'isha': 7
}


def get_today_prayers():
    """Возвращает отформатированное расписание на сегодня"""
    conn = get_connection()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        row = get_by_date(conn, today)

        if not row:
            return "❌ Нет данных на сегодня. Запустите парсинг."

        # Получаем время Шурук, если оно есть
        shurooq_time = row[COLUMN_INDEXES['shurooq']] if row[COLUMN_INDEXES['shurooq']] else "—"
        
        return (
            f"🕌 <b>Намазы на сегодня</b>\n"
            f"📅 {today}\n\n"
            f"🌅 Фаджр: {row[COLUMN_INDEXES['fajr']]}\n"
            f"🌄 Шурук: {shurooq_time}\n"
            f"☀️ Зухр: {row[COLUMN_INDEXES['dhuhr']]}\n"
            f"🏜️ Аср: {row[COLUMN_INDEXES['asr']]}\n"
            f"🌇 Магриб: {row[COLUMN_INDEXES['maghrib']]}\n"
            f"🌙 Иша: {row[COLUMN_INDEXES['isha']]}"
        )
    finally:
        conn.close()


def get_prayers_for_date(date_str):
    """Возвращает расписание на конкретную дату"""
    conn = get_connection()
    try:
        row = get_by_date(conn, date_str)
        if not row:
            return None
        return {
            "date": row[COLUMN_INDEXES['date']],
            "fajr": row[COLUMN_INDEXES['fajr']],
            "shurooq": row[COLUMN_INDEXES['shurooq']],
            "dhuhr": row[COLUMN_INDEXES['dhuhr']],
            "asr": row[COLUMN_INDEXES['asr']],
            "maghrib": row[COLUMN_INDEXES['maghrib']],
            "isha": row[COLUMN_INDEXES['isha']]
        }
    finally:
        conn.close()


def get_next_prayer():
    """Возвращает следующий намаз (сегодня или завтра)"""
    conn = get_connection()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # Получаем расписание на сегодня
    today_row = get_by_date(conn, today)
    
    if not today_row:
        return "❌ Нет данных на сегодня"

    # Проверяем намазы на сегодня
    prayers_today = [
        ("Фаджр", today_row[COLUMN_INDEXES['fajr']]),
        ("Зухр", today_row[COLUMN_INDEXES['dhuhr']]),
        ("Аср", today_row[COLUMN_INDEXES['asr']]),
        ("Магриб", today_row[COLUMN_INDEXES['maghrib']]),
        ("Иша", today_row[COLUMN_INDEXES['isha']]),
    ]

    for name, time_str in prayers_today:
        try:
            prayer_time = datetime.strptime(time_str, "%H:%M").replace(
                year=now.year,
                month=now.month,
                day=now.day
            )

            if prayer_time > now:
                diff = prayer_time - now
                hours, remainder = divmod(diff.seconds, 3600)
                minutes = remainder // 60

                return (
                    f"🕌 <b>Следующий намаз:</b> {name}\n"
                    f"⏰ Время: {time_str}\n"
                    f"⌛ Через: {hours} ч {minutes} мин"
                )
        except ValueError:
            # Пропускаем невалидное время
            continue

    # Если все намазы на сегодня прошли, ищем Фаджр на завтра
    from datetime import timedelta
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow_row = get_by_date(conn, tomorrow)
    
    if tomorrow_row:
        fajr_tomorrow = tomorrow_row[COLUMN_INDEXES['fajr']]
        try:
            # Время Фаджра на завтра
            fajr_time = datetime.strptime(fajr_tomorrow, "%H:%M").replace(
                year=now.year,
                month=now.month,
                day=now.day
            )
            # Добавляем 1 день для завтрашнего Фаджра
            fajr_time = fajr_time + timedelta(days=1)
            
            diff = fajr_time - now
            hours, remainder = divmod(diff.seconds, 3600)
            minutes = remainder // 60
            
            return (
                f"🌙 <b>Все намазы на сегодня завершены</b>\n\n"
                f"🕌 <b>Следующий намаз:</b> Фаджр (завтра)\n"
                f"⏰ Время: {fajr_tomorrow}\n"
                f"⌛ Через: {hours} ч {minutes} мин"
            )
        except ValueError:
            pass
    
    # Если нет данных на завтра
    return "🌙 На сегодня намазы завершены. Нет данных на завтра."