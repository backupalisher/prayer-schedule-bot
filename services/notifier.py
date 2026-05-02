import asyncio
from datetime import datetime, timedelta
import pytz
import logging
from aiogram.exceptions import TelegramForbiddenError
from settings import USE_TELEGRAM, BOT_TOKEN, CHAT_ID
from db.database import get_connection
from db.crud import get_all_users, get_prayer_by_date_and_name, update_user_subscription

# Настройка логирования
logger = logging.getLogger(__name__)

# Временная зона Москвы
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Словарь соответствия названий намазов и столбцов в БД
PRAYER_TIMES = {
    "Фаджр": "fajr",
    "Шурук": "shurooq",
    "Зухр": "dhuhr",
    "Аср": "asr",
    "Магриб": "maghrib",
    "Иша": "isha",
}

# Эмодзи для каждого намаза
PRAYER_EMOJIS = {
    "Фаджр": "🌅",
    "Шурук": "🌄",
    "Зухр": "☀️",
    "Аср": "🏜️",
    "Магриб": "🌇",
    "Иша": "🌙",
}


async def send_telegram_message(text, chat_id=None, max_retries=3, timeout=10):
    """Отправляет сообщение в Telegram с повторными попытками и таймаутами"""
    if not USE_TELEGRAM or not BOT_TOKEN:
        logger.info("🔔 %s", text)
        return False

    # Если chat_id не указан, используем CHAT_ID из настроек
    if chat_id is None:
        if not CHAT_ID:
            logger.info("🔔 %s", text)
            return False
        chat_id = CHAT_ID

    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Используем общий экземпляр бота (локальный импорт для избежания циклического импорта)
            from bot.bot import get_bot
            bot = get_bot()
            
            # Отправляем сообщение с таймаутом
            await asyncio.wait_for(
                bot.send_message(chat_id=chat_id, text=text),
                timeout=timeout
            )
            
            logger.info("✅ Сообщение отправлено в Telegram (chat_id: %s): %s...", chat_id, text[:50])
            return True
            
        except asyncio.TimeoutError:
            last_error = f"Таймаут ({timeout} секунд) при отправке сообщения"
            logger.warning("⚠️ Попытка %s/%s: %s", attempt + 1, max_retries, last_error)
            
        except TelegramForbiddenError:
            # Бот заблокирован пользователем — деактивируем его
            logger.warning("🚫 Бот заблокирован пользователем %s, деактивирую подписку", chat_id)
            try:
                conn = get_connection()
                update_user_subscription(conn, chat_id, 0)
                conn.close()
                logger.info("✅ Подписка пользователя %s деактивирована", chat_id)
            except Exception as db_err:
                logger.error("❌ Ошибка при деактивации пользователя %s: %s", chat_id, db_err)
            # Не повторяем отправку для заблокированного пользователя
            return False
            
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)}"
            logger.warning("⚠️ Попытка %s/%s: %s", attempt + 1, max_retries, last_error)
            
        # Экспоненциальная задержка между попытками
        if attempt < max_retries - 1:
            delay = 2 ** attempt  # 1, 2, 4 секунды
            logger.info("⏳ Повтор через %s секунд...", delay)
            await asyncio.sleep(delay)
    
    # Все попытки исчерпаны
    logger.error("❌ Не удалось отправить сообщение в Telegram (chat_id: %s) после %s попыток", chat_id, max_retries)
    logger.error("   Последняя ошибка: %s", last_error)
    logger.error("   Текст сообщения: %s", text)
    return False


async def send_telegram_message_to_all(text, max_retries=3, timeout=10):
    """Отправляет сообщение всем пользователям из БД"""
    if not USE_TELEGRAM or not BOT_TOKEN:
        logger.info("🔔 %s", text)
        return 0
    
    # Получаем всех пользователей из БД
    conn = get_connection()
    users = get_all_users(conn)
    conn.close()
    
    if not users:
        logger.warning("⚠️ Нет пользователей в БД для отправки уведомлений")
        return 0
    
    logger.info("📨 Отправка уведомления %s пользователям: %s...", len(users), text[:50])
    
    success_count = 0
    for user in users:
        chat_id = user[1]  # chat_id находится во втором столбце
        try:
            success = await send_telegram_message(text, chat_id=chat_id, max_retries=max_retries, timeout=timeout)
            if success:
                success_count += 1
        except Exception as e:
            logger.error("❌ Ошибка при отправке пользователю %s: %s", chat_id, e)
    
    logger.info("📊 Итог: отправлено %s из %s пользователям", success_count, len(users))
    return success_count


async def notify_async(prayer_name):
    """Асинхронное уведомление о времени намаза"""
    # Получаем время намаза из БД
    prayer_time = await get_prayer_time_from_db(prayer_name)
    emoji = PRAYER_EMOJIS.get(prayer_name, "🕌")
    
    if prayer_time:
        message = f"🕌 Время намаза: {emoji} {prayer_name}: {prayer_time}"
    else:
        message = f"🕌 Время намаза: {prayer_name}"
    
    logger.info("🔔 %s", message)
    
    try:
        success_count = await send_telegram_message_to_all(message)
        if success_count > 0:
            logger.info("✅ Уведомление '%s' успешно отправлено %s пользователям", prayer_name, success_count)
            return True
        else:
            logger.warning("❌ Не удалось отправить уведомление '%s' ни одному пользователю", prayer_name)
            return False
    except Exception as e:
        logger.error("❌ Критическая ошибка при отправке уведомления '%s': %s", prayer_name, e)
        return False


def notify(prayer_name):
    """Синхронная обертка для уведомления (для использования из планировщика)"""
    # Получаем время намаза из БД (синхронно)
    prayer_time = None
    try:
        from db.crud import get_prayer_by_date_and_name
        conn = get_connection()
        today_str = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
        prayer_time = get_prayer_by_date_and_name(conn, today_str, prayer_name)
        conn.close()
    except Exception as e:
        logger.warning("⚠️ Не удалось получить время из БД: %s", e)

    emoji = PRAYER_EMOJIS.get(prayer_name, "🕌")

    if prayer_time:
        message = f"🕌 Время намаза: {emoji} {prayer_name}: {prayer_time}"
    else:
        message = f"🕌 Время намаза: {prayer_name}"

    logger.info("🔔 %s", message)
    
    if not USE_TELEGRAM or not BOT_TOKEN:
        logger.warning("⚠️ Telegram отключен в настройках")
        return 0
    
    # Для синхронного вызова создаем новый event loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success_count = loop.run_until_complete(send_telegram_message_to_all(message))
        
        if success_count > 0:
            logger.info("✅ Уведомление '%s' успешно отправлено %s пользователям (синхронно)", prayer_name, success_count)
        else:
            logger.warning("❌ Не удалось отправить уведомление '%s' ни одному пользователю (синхронно)", prayer_name)
        
        return success_count
    except RuntimeError as e:
        if "There is no current event loop" in str(e):
            # Пытаемся использовать существующий event loop
            try:
                loop = asyncio.get_event_loop()
                success_count = loop.run_until_complete(send_telegram_message_to_all(message))
                logger.info("✅ Использован существующий event loop для '%s'", prayer_name)
                return success_count
            except Exception:
                pass
        logger.error("❌ Ошибка event loop для '%s': %s", prayer_name, e)
        return 0
    except Exception as e:
        logger.error("❌ Критическая ошибка при отправке уведомления '%s': %s", prayer_name, e)
        return 0
    finally:
        try:
            if 'loop' in locals() and not loop.is_closed():
                loop.close()
        except Exception:
            pass


async def get_prayer_time_from_db(prayer_name: str, target_date: str = None) -> str:
    """
    Получает время намаза из БД по названию и дате.
    
    Args:
        prayer_name: Название намаза (Фаджр, Шурук, Зухр, Аср, Магриб, Иша)
        target_date: Дата в формате ГГГГ-ММ-ДД (если None - сегодня)
    
    Returns:
        str: Время в формате ЧЧ:ММ или None если не найдено
    """
    if target_date is None:
        target_date = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
    
    conn = get_connection()
    try:
        time_str = get_prayer_by_date_and_name(conn, target_date, prayer_name)
        return time_str
    finally:
        conn.close()


def get_today_prayers():
    """Возвращает отформатированное расписание на сегодня"""
    from db.crud import get_by_date
    conn = get_connection()
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        row = get_by_date(conn, today)

        if not row:
            return "❌ Нет данных на сегодня. Запустите парсинг."

        # row[0]=id, row[1]=date, row[2]=fajr, row[3]=shurooq,
        # row[4]=dhuhr, row[5]=asr, row[6]=maghrib, row[7]=isha
        shurooq_time = row[3] if row[3] else "—"

        return (
            f"🕌 <b>Намазы на сегодня</b>\n"
            f"📅 {today}\n\n"
            f"🌅 Фаджр: {row[2]}\n"
            f"🌄 Шурук: {shurooq_time}\n"
            f"☀️ Зухр: {row[4]}\n"
            f"🏜️ Аср: {row[5]}\n"
            f"🌇 Магриб: {row[6]}\n"
            f"🌙 Иша: {row[7]}"
        )
    finally:
        conn.close()


def get_next_prayer():
    """Возвращает следующий намаз (сегодня или завтра)"""
    from db.crud import get_by_date
    conn = get_connection()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    # Получаем расписание на сегодня
    today_row = get_by_date(conn, today)

    if not today_row:
        return "❌ Нет данных на сегодня"

    # Проверяем намазы на сегодня (все 6 намазов)
    prayers_today = [
        ("Фаджр", today_row[2]),
        ("Шурук", today_row[3]),
        ("Зухр", today_row[4]),
        ("Аср", today_row[5]),
        ("Магриб", today_row[6]),
        ("Иша", today_row[7]),
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
            continue

    # Если все намазы на сегодня прошли, ищем Фаджр на завтра
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    tomorrow_row = get_by_date(conn, tomorrow)

    if tomorrow_row:
        fajr_tomorrow = tomorrow_row[2]
        try:
            fajr_time = datetime.strptime(fajr_tomorrow, "%H:%M").replace(
                year=now.year,
                month=now.month,
                day=now.day
            )
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

    return "🌙 На сегодня намазы завершены. Нет данных на завтра."


async def prayer_time_worker():
    """
    Фоновая задача, которая каждые 30 секунд проверяет,
    не наступило ли время очередного намаза, и отправляет уведомление.
    Работает на основе данных из БД.
    """
    logger.info("🔄 Запуск фонового worker'а проверки времени намазов...")
    
    # Множество для отслеживания уже отправленных уведомлений сегодня
    # Ключ: "YYYY-MM-DD_PrayerName"
    sent_notifications = set()
    
    # Сбрасываем при каждом запуске (на случай перезапуска бота)
    # Чтобы не пропустить уведомления, которые могли быть не отправлены
    
    while True:
        try:
            now = datetime.now(MOSCOW_TZ)
            today = now.strftime("%Y-%m-%d")
            current_time_str = now.strftime("%H:%M")
            
            # Каждые 30 секунд проверяем все намазы
            for prayer_name in PRAYER_TIMES:
                notification_key = f"{today}_{prayer_name}"
                
                # Пропускаем, если уже отправили уведомление
                if notification_key in sent_notifications:
                    continue
                
                # Получаем время намаза из БД
                prayer_time = await get_prayer_time_from_db(prayer_name, today)
                
                if not prayer_time:
                    continue
                
                # Сравниваем текущее время с временем намаза
                if current_time_str == prayer_time:
                    logger.info("⏰ Наступило время намаза '%s' в %s", prayer_name, prayer_time)
                    
                    # Отправляем уведомление
                    await notify_async(prayer_name)
                    
                    # Отмечаем как отправленное
                    sent_notifications.add(notification_key)
            
            # Очистка устаревших записей (на следующий день)
            # Удаляем все записи не за сегодня
            keys_to_remove = [k for k in sent_notifications if not k.startswith(today)]
            for k in keys_to_remove:
                sent_notifications.discard(k)
            
            # Ждём 30 секунд перед следующей проверкой
            # (меньше минуты, чтобы не пропустить начало намаза)
            await asyncio.sleep(30)
            
        except asyncio.CancelledError:
            logger.info("🛑 Фоновый worker проверки времени намазов остановлен")
            break
        except Exception as e:
            logger.error("❌ Ошибка в prayer_time_worker: %s", e)
            import traceback
            traceback.print_exc()
            await asyncio.sleep(30)
