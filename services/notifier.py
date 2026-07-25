import asyncio
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo
import logging
from aiogram.exceptions import TelegramForbiddenError
from settings import USE_TELEGRAM, BOT_TOKEN, CHAT_ID
from db.database import get_connection
from db.crud import (
    get_all_users,
    get_user_by_chat_id,
    get_user_prayer_by_date_and_name,
    get_user_prayers_by_date,
    get_users_with_location,
    update_user_subscription,
    user_has_location,
)
from services.user_schedule import ensure_user_current_month

logger = logging.getLogger(__name__)

PRAYER_TIMES = {
    "Фаджр": "fajr",
    "Шурук": "shurooq",
    "Зухр": "dhuhr",
    "Аср": "asr",
    "Магриб": "maghrib",
    "Иша": "isha",
}

PRAYER_EMOJIS = {
    "Фаджр": "🌅",
    "Шурук": "🌄",
    "Зухр": "☀️",
    "Аср": "🏜️",
    "Магриб": "🌇",
    "Иша": "🌙",
}

NO_LOCATION_TEXT = (
    "📍 Сначала отправьте геолокацию.\n"
    "Нажмите кнопку «📍 Отправить локацию» или команду /location."
)


async def send_telegram_message(text, chat_id=None, max_retries=3, timeout=10):
    """Отправляет сообщение в Telegram с повторными попытками и таймаутами."""
    if not USE_TELEGRAM or not BOT_TOKEN:
        logger.info("🔔 %s", text)
        return False

    if chat_id is None:
        if not CHAT_ID:
            logger.info("🔔 %s", text)
            return False
        chat_id = CHAT_ID

    last_error = None

    for attempt in range(max_retries):
        try:
            from bot.bot import get_bot
            bot = get_bot()

            await asyncio.wait_for(
                bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML"),
                timeout=timeout,
            )

            logger.info("✅ Сообщение отправлено в Telegram (chat_id: %s): %s...", chat_id, text[:50])
            return True

        except asyncio.TimeoutError:
            last_error = f"Таймаут ({timeout} секунд) при отправке сообщения"
            logger.warning("⚠️ Попытка %s/%s: %s", attempt + 1, max_retries, last_error)

        except TelegramForbiddenError:
            logger.warning("🚫 Бот заблокирован пользователем %s, деактивирую подписку", chat_id)
            try:
                conn = get_connection()
                update_user_subscription(conn, chat_id, 0)
                conn.close()
                logger.info("✅ Подписка пользователя %s деактивирована", chat_id)
            except Exception as db_err:
                logger.error("❌ Ошибка при деактивации пользователя %s: %s", chat_id, db_err)
            return False

        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)}"
            logger.warning("⚠️ Попытка %s/%s: %s", attempt + 1, max_retries, last_error)

        if attempt < max_retries - 1:
            delay = 2 ** attempt
            logger.info("⏳ Повтор через %s секунд...", delay)
            await asyncio.sleep(delay)

    logger.error(
        "❌ Не удалось отправить сообщение в Telegram (chat_id: %s) после %s попыток",
        chat_id, max_retries,
    )
    logger.error("   Последняя ошибка: %s", last_error)
    return False


async def send_telegram_message_to_all(text, max_retries=3, timeout=10):
    """Отправляет сообщение всем пользователям из БД."""
    if not USE_TELEGRAM or not BOT_TOKEN:
        logger.info("🔔 %s", text)
        return 0

    conn = get_connection()
    users = get_all_users(conn)
    conn.close()

    if not users:
        logger.warning("⚠️ Нет пользователей в БД для отправки уведомлений")
        return 0

    logger.info("📨 Отправка уведомления %s пользователям: %s...", len(users), text[:50])

    success_count = 0
    for user in users:
        chat_id = user["chat_id"]
        try:
            success = await send_telegram_message(
                text, chat_id=chat_id, max_retries=max_retries, timeout=timeout
            )
            if success:
                success_count += 1
        except Exception as e:
            logger.error("❌ Ошибка при отправке пользователю %s: %s", chat_id, e)

    logger.info("📊 Итог: отправлено %s из %s пользователям", success_count, len(users))
    return success_count


async def notify_user_prayer(chat_id: str, prayer_name: str, prayer_time: str) -> bool:
    """Отправляет уведомление одному пользователю о наступлении намаза."""
    emoji = PRAYER_EMOJIS.get(prayer_name, "🕌")
    message = f"🕌 Время намаза: {emoji} {prayer_name}: {prayer_time}"
    logger.info("🔔 chat_id=%s %s", chat_id, message)
    return await send_telegram_message(message, chat_id=chat_id)


def get_today_prayers(chat_id: Optional[str | int] = None) -> str:
    """Возвращает персональное расписание на сегодня для пользователя."""
    if chat_id is None:
        return NO_LOCATION_TEXT

    conn = get_connection()
    try:
        user = get_user_by_chat_id(conn, chat_id)
        if not user_has_location(user):
            return NO_LOCATION_TEXT

        tz_name = user["timezone"]
        method = user["calculation_method"] or "auto"
        tz = ZoneInfo(tz_name)
        today = datetime.now(tz).strftime("%Y-%m-%d")
        row = get_user_prayers_by_date(conn, chat_id, today)
    finally:
        conn.close()

    if not row:
        ensure_user_current_month(chat_id)
        conn = get_connection()
        try:
            row = get_user_prayers_by_date(conn, chat_id, today)
        finally:
            conn.close()

    if not row:
        return "❌ Не удалось рассчитать расписание. Отправьте локацию ещё раз."

    return (
        f"🕌 <b>Намазы на сегодня</b>\n"
        f"📅 {today} ({tz_name})\n"
        f"🧭 Метод: <code>{method}</code>\n\n"
        f"🌅 Фаджр: {row['fajr']}\n"
        f"🌄 Шурук: {row['shurooq'] or '—'}\n"
        f"☀️ Зухр: {row['dhuhr']}\n"
        f"🏜️ Аср: {row['asr']}\n"
        f"🌇 Магриб: {row['maghrib']}\n"
        f"🌙 Иша: {row['isha']}"
    )


def get_next_prayer(chat_id: Optional[str | int] = None) -> str:
    """Возвращает следующий намаз для конкретного пользователя."""
    if chat_id is None:
        return NO_LOCATION_TEXT

    conn = get_connection()
    try:
        user = get_user_by_chat_id(conn, chat_id)
        if not user_has_location(user):
            return NO_LOCATION_TEXT
        tz_name = user["timezone"]
    finally:
        conn.close()

    tz = ZoneInfo(tz_name)
    now = datetime.now(tz)
    today = now.strftime("%Y-%m-%d")

    conn = get_connection()
    try:
        today_row = get_user_prayers_by_date(conn, chat_id, today)
    finally:
        conn.close()

    if not today_row:
        ensure_user_current_month(chat_id)
        conn = get_connection()
        try:
            today_row = get_user_prayers_by_date(conn, chat_id, today)
        finally:
            conn.close()

    if not today_row:
        return "❌ Нет данных на сегодня. Отправьте локацию через /location."

    prayers_today = [
        ("Фаджр", today_row["fajr"]),
        ("Шурук", today_row["shurooq"]),
        ("Зухр", today_row["dhuhr"]),
        ("Аср", today_row["asr"]),
        ("Магриб", today_row["maghrib"]),
        ("Иша", today_row["isha"]),
    ]

    for name, time_str in prayers_today:
        if not time_str:
            continue
        try:
            prayer_time = datetime.strptime(time_str, "%H:%M").replace(
                year=now.year,
                month=now.month,
                day=now.day,
                tzinfo=tz,
            )
            if prayer_time > now:
                diff = prayer_time - now
                total_seconds = int(diff.total_seconds())
                hours, remainder = divmod(total_seconds, 3600)
                minutes = remainder // 60
                return (
                    f"🕌 <b>Следующий намаз:</b> {name}\n"
                    f"⏰ Время: {time_str}\n"
                    f"⌛ Через: {hours} ч {minutes} мин\n"
                    f"🌍 TZ: {tz_name}"
                )
        except ValueError:
            continue

    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = get_connection()
    try:
        tomorrow_row = get_user_prayers_by_date(conn, chat_id, tomorrow)
    finally:
        conn.close()

    if tomorrow_row and tomorrow_row["fajr"]:
        fajr_tomorrow = tomorrow_row["fajr"]
        try:
            fajr_time = datetime.strptime(fajr_tomorrow, "%H:%M").replace(
                year=now.year,
                month=now.month,
                day=now.day,
                tzinfo=tz,
            ) + timedelta(days=1)
            diff = fajr_time - now
            total_seconds = int(diff.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes = remainder // 60
            return (
                f"🌙 <b>Все намазы на сегодня завершены</b>\n\n"
                f"🕌 <b>Следующий намаз:</b> Фаджр (завтра)\n"
                f"⏰ Время: {fajr_tomorrow}\n"
                f"⌛ Через: {hours} ч {minutes} мин"
            )
        except ValueError:
            pass

    return "🌙 На сегодня намазы завершены. Нет данных на завтра."


async def prayer_time_worker():
    """
    Фоновая задача: каждые 30 секунд проверяет локальное время каждого пользователя
    и отправляет персональные уведомления о намазе.
    """
    logger.info("🔄 Запуск фонового worker'а персональных уведомлений...")

    # Ключ: "chat_id_YYYY-MM-DD_PrayerName"
    sent_notifications: set[str] = set()

    while True:
        try:
            conn = get_connection()
            users = get_users_with_location(conn)
            conn.close()

            for user in users:
                chat_id = str(user["chat_id"])
                tz_name = user["timezone"]
                try:
                    tz = ZoneInfo(tz_name)
                except Exception:
                    logger.warning("⚠️ Некорректный TZ у пользователя %s: %s", chat_id, tz_name)
                    continue

                now = datetime.now(tz)
                today = now.strftime("%Y-%m-%d")
                current_time_str = now.strftime("%H:%M")

                for prayer_name in PRAYER_TIMES:
                    notification_key = f"{chat_id}_{today}_{prayer_name}"
                    if notification_key in sent_notifications:
                        continue

                    conn = get_connection()
                    try:
                        prayer_time = get_user_prayer_by_date_and_name(
                            conn, chat_id, today, prayer_name
                        )
                    finally:
                        conn.close()

                    if not prayer_time:
                        continue

                    if current_time_str == prayer_time:
                        logger.info(
                            "⏰ chat_id=%s намаз '%s' в %s (%s)",
                            chat_id, prayer_name, prayer_time, tz_name,
                        )
                        await notify_user_prayer(chat_id, prayer_name, prayer_time)
                        sent_notifications.add(notification_key)

            # Чистим ключи не за сегодняшние даты пользователей постепенно:
            # оставляем только ключи, содержащие одну из «свежих» дат.
            if len(sent_notifications) > 5000:
                sent_notifications.clear()

            await asyncio.sleep(30)

        except asyncio.CancelledError:
            logger.info("🛑 Фоновый worker персональных уведомлений остановлен")
            break
        except Exception as e:
            logger.error("❌ Ошибка в prayer_time_worker: %s", e)
            import traceback
            traceback.print_exc()
            await asyncio.sleep(30)
