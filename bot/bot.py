from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BotCommand, ErrorEvent
from aiogram.filters import Command
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramConflictError
import asyncio
import threading
import os
import sys
import logging
from datetime import datetime

from settings import BOT_TOKEN, CHAT_ID
from services.notifier import get_today_prayers, get_next_prayer
from services.pdf_generator import generate_pdf, async_generate_pdf
from db.database import get_connection
from db.crud import insert_or_update_user, update_user_subscription, delete_user

from aiogram.types import FSInputFile

# Названия месяцев для подписей
MONTH_NAMES = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

# Настройка логирования
logger = logging.getLogger(__name__)

# Используем потокобезопасную инициализацию бота
_bot_instance = None
_bot_lock = threading.Lock()
dp = Dispatcher()


def init_bot():
    """Инициализирует бота (потокобезопасно)"""
    global _bot_instance

    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN не найден в .env")

    with _bot_lock:
        if _bot_instance is None:
            _bot_instance = Bot(token=BOT_TOKEN)
            logger.info("✅ Бот инициализирован")
    
    return _bot_instance


def get_bot():
    """Возвращает экземпляр бота (создает при необходимости)"""
    if _bot_instance is None:
        return init_bot()
    return _bot_instance


async def save_user_info(message: Message):
    """Сохраняет информацию о пользователе в БД"""
    try:
        conn = get_connection()
        chat_id = message.chat.id
        username = message.from_user.username
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        
        success = insert_or_update_user(conn, chat_id, username, first_name, last_name)
        conn.close()
        
        if success:
            logger.info("✅ Пользователь %s сохранен в БД", chat_id)
        else:
            logger.warning("⚠️ Не удалось сохранить пользователя %s", chat_id)
    except Exception as e:
        logger.error("❌ Ошибка при сохранении пользователя: %s", e)


async def handle_forbidden_error(chat_id: int, context: str = ""):
    """
    Обрабатывает ошибку TelegramForbiddenError.
    Удаляет пользователя из БД, если бот был заблокирован или кикнут.
    """
    logger.warning("🚫 Бот заблокирован пользователем %s или кикнут из чата (%s)", chat_id, context)
    try:
        conn = get_connection()
        # Отписываем пользователя (удаляем или деактивируем)
        update_user_subscription(conn, chat_id, 0)
        conn.close()
        logger.info("✅ Пользователь %s деактивирован (подписка отключена)", chat_id)
    except Exception as e:
        logger.error("❌ Ошибка при деактивации пользователя %s: %s", chat_id, e)


@dp.errors()
async def errors_handler(event: ErrorEvent):
    """
    Глобальный обработчик ошибок aiogram.
    Предотвращает падение бота при любых исключениях.
    """
    exception = event.exception
    update = event.update
    
    logger.error("⚠️ Глобальная ошибка: %s: %s", type(exception).__name__, exception)
    
    # Обработка Forbidden (бот заблокирован/кикнут)
    if isinstance(exception, TelegramForbiddenError):
        # Пытаемся извлечь chat_id из update
        chat_id = None
        if update and update.message:
            chat_id = update.message.chat.id
        elif update and update.callback_query:
            chat_id = update.callback_query.message.chat.id
        
        if chat_id:
            await handle_forbidden_error(chat_id, "global_handler")
    
    # Возвращаем True, чтобы предотвратить всплытие исключения
    return True


@dp.message(Command("start"))
async def start_handler(message: Message):
    """Обработчик команды /start"""
    try:
        # Сохраняем пользователя в БД
        await save_user_info(message)
        
        await message.answer(
            "🕌 <b>Ассаламу алейкум!</b>\n\n"
            "Я бот расписания намазов.\n\n"
            "📋 <b>Доступные команды:</b>\n"
            "/today - расписание на сегодня\n"
            "/next - следующий намаз\n"
            "/pdf - скачать PDF расписание\n"
            "/help - помощь\n\n"
            "<i>Ваш chat_id автоматически сохранен для получения уведомлений</i>",
            parse_mode="HTML"
        )
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "start_handler")
    except Exception as e:
        logger.error("❌ Ошибка в start_handler: %s", e)


@dp.message(Command("help"))
async def help_handler(message: Message):
    """Обработчик команды /help"""
    try:
        # Сохраняем пользователя в БД
        await save_user_info(message)
        
        await message.answer(
            "🕌 <b>Помощь по командам:</b>\n\n"
            "/today - показывает время намазов на сегодня\n"
            "/next - показывает следующий намаз\n"
            "/pdf - генерирует и отправляет PDF файл с расписанием на месяц\n\n"
            "<i>Бот автоматически присылает уведомления о времени намазов</i>",
            parse_mode="HTML"
        )
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "help_handler")
    except Exception as e:
        logger.error("❌ Ошибка в help_handler: %s", e)


@dp.message(Command("today"))
async def today_handler(message: Message):
    """Обработчик команды /today"""
    try:
        # Сохраняем пользователя в БД
        await save_user_info(message)
        
        text = get_today_prayers()
        await message.answer(text, parse_mode="HTML")
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "today_handler")
    except Exception as e:
        logger.error("❌ Ошибка в today_handler: %s", e)


@dp.message(Command("pdf"))
async def pdf_handler(message: Message):
    try:
        # Сохраняем пользователя в БД
        await save_user_info(message)

        now = datetime.now()
        year = now.year
        month = now.month

        await message.answer("📄 Генерирую PDF файл с расписанием...")

        pdf_file = await async_generate_pdf(year, month)

        if pdf_file:
            file = FSInputFile(pdf_file)

            try:
                await message.answer_document(
                    document=file,
                    caption=f"📊 Расписание намазов на {MONTH_NAMES[month]} {year}"
                )
                # Удаляем файл после успешной отправки
                os.remove(pdf_file)
                logger.info("PDF файл %s удалён после отправки", pdf_file)
            except TelegramForbiddenError:
                await handle_forbidden_error(message.chat.id, "pdf_handler")
                # Не удаляем файл, т.к. отправка не удалась
            except Exception as e:
                logger.error("Ошибка отправки PDF: %s", e)
                # Оставляем файл для отладки
                raise
        else:
            await message.answer("❌ Не удалось сгенерировать PDF. Возможно, нет данных для текущего месяца.")
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "pdf_handler_outer")
    except Exception as e:
        logger.error("❌ Ошибка в pdf_handler: %s", e)


@dp.message(Command("next"))
async def next_handler(message: Message):
    try:
        # Сохраняем пользователя в БД
        await save_user_info(message)
        
        text = get_next_prayer()
        await message.answer(text, parse_mode="HTML")
    except TelegramForbiddenError:
        await handle_forbidden_error(message.chat.id, "next_handler")
    except Exception as e:
        logger.error("❌ Ошибка в next_handler: %s", e)


@dp.message()
async def debug_handler(message: Message):
    """Обработчик всех остальных сообщений"""
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
    """Отправляет сообщение в указанный чат"""
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
    """Запускает бота"""
    bot_instance = init_bot()

    # Принудительно удаляем webhook перед стартом polling
    # Это гарантирует, что не будет конфликта между webhook и polling
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
    conflict_retries = 0

    while conflict_retries < max_conflict_retries:
        try:
            await dp.start_polling(bot_instance)
            break  # Нормальное завершение polling
        except TelegramConflictError as e:
            conflict_retries += 1
            logger.error(
                "🚫 TelegramConflictError: %s. "
                "Попытка %s/%s. "
                "Убедитесь, что только один экземпляр бота запущен с токеном %s...",
                e, conflict_retries, max_conflict_retries, BOT_TOKEN[:8] + "..."
            )
            if conflict_retries >= max_conflict_retries:
                logger.critical(
                    "🚫 КРИТИЧЕСКАЯ ОШИБКА: TelegramConflictError не устранён после %s попыток. "
                    "Завершение работы. Возможные причины:\n"
                    "  1. Другой экземпляр бота запущен в другом терминале/сессии\n"
                    "  2. Бот запущен на другом сервере\n"
                    "  3. Предыдущий процесс не был завершён корректно\n"
                    "Решение: завершите все процессы main.py и запустите бот снова.",
                    max_conflict_retries
                )
                raise
            await asyncio.sleep(5)
