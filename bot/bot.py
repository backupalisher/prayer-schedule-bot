from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    BotCommand,
    ErrorEvent,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    FSInputFile,
)
from aiogram.filters import Command
from aiogram.exceptions import TelegramForbiddenError, TelegramConflictError
import asyncio
import threading
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from settings import BOT_TOKEN, CHAT_ID
from services.notifier import get_today_prayers, get_next_prayer
from services.pdf_generator import async_generate_pdf
from services.user_schedule import save_location_and_recalculate
from db.database import get_connection
from db.crud import (
    insert_or_update_user,
    update_user_subscription,
    get_user_by_chat_id,
    user_has_location,
)

MONTH_NAMES = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

logger = logging.getLogger(__name__)

_bot_instance = None
_bot_lock = threading.Lock()
dp = Dispatcher()


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📍 Отправить локацию", request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def init_bot():
    """Инициализирует бота (потокобезопасно)."""
    global _bot_instance

    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN не найден в .env")

    with _bot_lock:
        if _bot_instance is None:
            _bot_instance = Bot(token=BOT_TOKEN)
            logger.info("✅ Бот инициализирован")

    return _bot_instance


def get_bot():
    """Возвращает экземпляр бота (создает при необходимости)."""
    if _bot_instance is None:
        return init_bot()
    return _bot_instance


async def save_user_info(message: Message) -> None:
    """Сохраняет базовую информацию о пользователе в БД."""
    try:
        conn = get_connection()
        try:
            success = insert_or_update_user(
                conn,
                message.chat.id,
                message.from_user.username,
                message.from_user.first_name,
                message.from_user.last_name,
            )
        finally:
            conn.close()

        if success:
            logger.info("✅ Пользователь %s сохранен в БД", message.chat.id)
        else:
            logger.warning("⚠️ Не удалось сохранить пользователя %s", message.chat.id)
    except Exception as e:
        logger.error("❌ Ошибка при сохранении пользователя: %s", e)


async def handle_forbidden_error(chat_id: int, context: str = "") -> None:
    """Деактивирует пользователя при блокировке бота."""
    logger.warning(
        "🚫 Бот заблокирован пользователем %s или кикнут из чата (%s)",
        chat_id, context,
    )
    try:
        conn = get_connection()
        try:
            update_user_subscription(conn, chat_id, 0)
        finally:
            conn.close()
        logger.info("✅ Пользователь %s деактивирован (подписка отключена)", chat_id)
    except Exception as e:
        logger.error("❌ Ошибка при деактивации пользователя %s: %s", chat_id, e)


@dp.errors()
async def errors_handler(event: ErrorEvent):
    """Глобальный обработчик ошибок aiogram."""
    exception = event.exception
    update = event.update

    logger.error("⚠️ Глобальная ошибка: %s: %s", type(exception).__name__, exception)

    if isinstance(exception, TelegramForbiddenError):
        chat_id = None
        if update and update.message:
            chat_id = update.message.chat.id
        elif update and update.callback_query and update.callback_query.message:
            chat_id = update.callback_query.message.chat.id

        if chat_id:
            await handle_forbidden_error(chat_id, "global_handler")

    return True


@dp.message(Command("start"))
async def start_handler(message: Message):
    """Обработчик команды /start."""
    try:
        await save_user_info(message)
        await message.answer(
            "🕌 <b>Ассаламу алейкум!</b>\n\n"
            "Я бот независимого расчёта времени намаза для любой точки мира.\n\n"
            "📍 Для начала отправьте вашу геолокацию — "
            "бот определит часовой пояс, выберет местный метод расчёта "
            "и сохранит персональное расписание.\n\n"
            "📋 <b>Команды:</b>\n"
            "/location — обновить геолокацию\n"
            "/today — расписание на сегодня\n"
            "/next — следующий намаз\n"
            "/pdf — PDF расписание на месяц\n"
            "/help — помощь",
            parse_mode="HTML",
            reply_markup=location_keyboard(),
        )
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "start_handler")
    except Exception as e:
        logger.error("❌ Ошибка в start_handler: %s", e)


@dp.message(Command("location"))
async def location_cmd_handler(message: Message):
    """Запрашивает обновление геолокации."""
    try:
        await save_user_info(message)
        await message.answer(
            "📍 Отправьте текущую геолокацию для пересчёта времени намаза.",
            reply_markup=location_keyboard(),
        )
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "location_cmd_handler")
    except Exception as e:
        logger.error("❌ Ошибка в location_cmd_handler: %s", e)


@dp.message(F.location)
async def location_handler(message: Message):
    """Принимает геолокацию, сохраняет настройки и пересчитывает намазы."""
    try:
        lat = message.location.latitude
        lon = message.location.longitude

        ok, tz_name, profile, today_times = save_location_and_recalculate(
            chat_id=message.chat.id,
            latitude=lat,
            longitude=lon,
            username=message.from_user.username if message.from_user else None,
            first_name=message.from_user.first_name if message.from_user else None,
            last_name=message.from_user.last_name if message.from_user else None,
        )

        if not ok or not tz_name or not profile or not today_times:
            await message.answer(
                "❌ Не удалось определить часовой пояс или рассчитать намазы.\n"
                "Попробуйте отправить локацию ещё раз.",
                reply_markup=location_keyboard(),
            )
            return

        text = (
            f"✅ <b>Локация сохранена, расписание пересчитано</b>\n\n"
            f"🌍 Часовой пояс: <code>{tz_name}</code>\n"
            f"📍 Координаты: <code>{lat:.4f}, {lon:.4f}</code>\n"
            f"🧭 Метод: {profile.label}\n\n"
            f"📅 <b>Намазы на сегодня:</b>\n"
            f"🌅 Фаджр: {today_times['Fajr']}\n"
            f"🌄 Шурук: {today_times['Sunrise']}\n"
            f"☀️ Зухр: {today_times['Dhuhr']}\n"
            f"🏜️ Аср: {today_times['Asr']}\n"
            f"🌇 Магриб: {today_times['Maghrib']}\n"
            f"🌙 Иша: {today_times['Isha']}"
        )
        await message.answer(
            text,
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "location_handler")
    except Exception as e:
        logger.error("❌ Ошибка в location_handler: %s", e)
        await message.answer("❌ Ошибка при обработке геолокации. Попробуйте ещё раз.")


@dp.message(Command("help"))
async def help_handler(message: Message):
    """Обработчик команды /help."""
    try:
        await save_user_info(message)
        await message.answer(
            "🕌 <b>Помощь по командам:</b>\n\n"
            "/location — отправить/обновить геолокацию\n"
            "/today — персональное время намазов на сегодня\n"
            "/next — следующий намаз по вашему часовому поясу\n"
            "/pdf — PDF с расписанием на месяц для вашей локации\n\n"
            "<i>Уведомления приходят индивидуально, по вашему местному времени.</i>\n"
            "<i>Метод расчёта подбирается автоматически "
            "(например, Umm al-Qura для Мекки, ДУМ РФ для России).</i>",
            parse_mode="HTML",
        )
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "help_handler")
    except Exception as e:
        logger.error("❌ Ошибка в help_handler: %s", e)


@dp.message(Command("today"))
async def today_handler(message: Message):
    """Обработчик команды /today."""
    try:
        await save_user_info(message)
        text = get_today_prayers(message.chat.id)
        markup = location_keyboard() if "геолокацию" in text.lower() else None
        await message.answer(text, parse_mode="HTML", reply_markup=markup)
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "today_handler")
    except Exception as e:
        logger.error("❌ Ошибка в today_handler: %s", e)


@dp.message(Command("pdf"))
async def pdf_handler(message: Message):
    try:
        await save_user_info(message)

        conn = get_connection()
        try:
            user = get_user_by_chat_id(conn, message.chat.id)
        finally:
            conn.close()

        if not user_has_location(user):
            await message.answer(
                "📍 Сначала отправьте геолокацию командой /location",
                reply_markup=location_keyboard(),
            )
            return

        tz = ZoneInfo(user["timezone"])
        now = datetime.now(tz)
        year = now.year
        month = now.month
        city = f"{user['latitude']:.2f}, {user['longitude']:.2f} ({user['timezone']})"

        await message.answer("📄 Генерирую PDF файл с вашим расписанием...")

        pdf_file = await async_generate_pdf(
            year,
            month,
            city=city,
            chat_id=str(message.chat.id),
        )

        if pdf_file:
            file = FSInputFile(pdf_file)
            try:
                await message.answer_document(
                    document=file,
                    caption=f"📊 Расписание намазов на {MONTH_NAMES[month]} {year}",
                )
                os.remove(pdf_file)
                logger.info("PDF файл %s удалён после отправки", pdf_file)
            except TelegramForbiddenError:
                await handle_forbidden_error(message.chat.id, "pdf_handler")
            except Exception as e:
                logger.error("Ошибка отправки PDF: %s", e)
                raise
        else:
            await message.answer(
                "❌ Не удалось сгенерировать PDF. "
                "Обновите локацию через /location и попробуйте снова."
            )
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "pdf_handler_outer")
    except Exception as e:
        logger.error("❌ Ошибка в pdf_handler: %s", e)


@dp.message(Command("next"))
async def next_handler(message: Message):
    try:
        await save_user_info(message)
        text = get_next_prayer(message.chat.id)
        markup = location_keyboard() if "геолокацию" in text.lower() else None
        await message.answer(text, parse_mode="HTML", reply_markup=markup)
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "next_handler")
    except Exception as e:
        logger.error("❌ Ошибка в next_handler: %s", e)


@dp.message()
async def debug_handler(message: Message):
    """Обработчик всех остальных сообщений."""
    try:
        logger.info("📨 Получено сообщение от %s: %s", message.chat.id, message.text)
        await message.answer(
            "❓ Неизвестная команда\n"
            "Используйте /help для списка команд"
        )
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "debug_handler")
    except Exception as e:
        logger.error("❌ Ошибка в debug_handler: %s", e)


async def send_message(text: str):
    """Отправляет сообщение в указанный чат."""
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN не найден в .env")

    if not CHAT_ID:
        logger.error("❌ CHAT_ID не задан")
        return

    try:
        bot = get_bot()
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")
    except TelegramForbiddenError:
        await handle_forbidden_error(CHAT_ID, "send_message")
    except Exception as e:
        logger.error("❌ Ошибка отправки сообщения: %s", e)


async def set_commands():
    bot_instance = get_bot()
    if not bot_instance:
        return

    commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="location", description="Обновить геолокацию"),
        BotCommand(command="today", description="Сегодня"),
        BotCommand(command="next", description="Следующий намаз"),
        BotCommand(command="pdf", description="Скачать PDF"),
        BotCommand(command="help", description="Помощь"),
    ]

    for i in range(3):
        try:
            await bot_instance.set_my_commands(commands)
            logger.info("✅ Команды установлены")
            return
        except Exception as e:
            logger.warning("⚠️ Попытка %s не удалась: %s", i + 1, e)
            await asyncio.sleep(2)


async def start_bot():
    """Запускает бота с автоматическим переподключением при сбоях polling."""
    bot_instance = init_bot()

    try:
        webhook_info = await bot_instance.get_webhook_info()
        if webhook_info.url:
            logger.warning("⚠️ Обнаружен активный webhook: %s. Удаляю...", webhook_info.url)
        await bot_instance.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Webhook очищен перед запуском polling")
    except Exception as e:
        logger.warning("⚠️ Не удалось проверить/очистить webhook: %s", e)

    await set_commands()
    logger.info("🚀 Бот запущен и готов к работе")

    max_conflict_retries = 5
    polling_retries = 0
    max_polling_retries = 100

    while polling_retries < max_polling_retries:
        conflict_retries = 0

        while conflict_retries < max_conflict_retries:
            try:
                await dp.start_polling(bot_instance)
                logger.warning("⚠️ Polling завершился без ошибки, перезапуск через 5 сек...")
                await asyncio.sleep(5)
                break
            except TelegramConflictError as e:
                conflict_retries += 1
                logger.error(
                    "🚫 TelegramConflictError: %s. Попытка %s/%s.",
                    e, conflict_retries, max_conflict_retries,
                )
                if conflict_retries >= max_conflict_retries:
                    logger.critical(
                        "🚫 TelegramConflictError не устранён. "
                        "Завершите другие экземпляры бота с тем же токеном."
                    )
                    raise
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                logger.info("🛑 Polling отменён")
                raise
            except Exception as e:
                polling_retries += 1
                delay = min(60, 5 * polling_retries)
                logger.error(
                    "❌ Ошибка polling (%s/%s): %s: %s. Перезапуск через %s сек...",
                    polling_retries, max_polling_retries, type(e).__name__, e, delay,
                )
                await asyncio.sleep(delay)
                break

    logger.critical("🚫 Превышен лимит перезапусков polling (%s)", max_polling_retries)
    raise RuntimeError("Polling failed after maximum retries")
