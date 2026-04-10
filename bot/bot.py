from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, BotCommand
from aiogram.filters import Command
import asyncio
import threading
import os
import logging

from config import BOT_TOKEN, CHAT_ID
from services.prayer_service import get_today_prayers
from services.pdf_generator import generate_pdf
from services.prayer_service import get_next_prayer

from aiogram.types import FSInputFile

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
            print("✅ Бот инициализирован")
    
    return _bot_instance


def get_bot():
    """Возвращает экземпляр бота (создает при необходимости)"""
    if _bot_instance is None:
        return init_bot()
    return _bot_instance


@dp.message(Command("start"))
async def start_handler(message: Message):
    """Обработчик команды /start"""
    await message.answer(
        "🕌 <b>Ассаламу алейкум!</b>\n\n"
        "Я бот расписания намазов.\n\n"
        "📋 <b>Доступные команды:</b>\n"
        "/today - расписание на сегодня\n"
        "/next - следующий намаз\n"
        "/pdf - скачать PDF расписание\n"
        "/help - помощь",
        parse_mode="HTML"
    )


@dp.message(Command("help"))
async def help_handler(message: Message):
    """Обработчик команды /help"""
    await message.answer(
        "🕌 <b>Помощь по командам:</b>\n\n"
        "/today - показывает время намазов на сегодня\n"
        "/next - показывает следующий намаз\n"
        "/pdf - генерирует и отправляет PDF файл с расписанием на месяц\n\n"
        "<i>Бот автоматически присылает уведомления о времени намазов</i>",
        parse_mode="HTML"
    )


@dp.message(Command("today"))
async def today_handler(message: Message):
    """Обработчик команды /today"""
    text = get_today_prayers()
    await message.answer(text, parse_mode="HTML")


@dp.message(Command("pdf"))
async def pdf_handler(message: Message):
    await message.answer("📄 Генерирую PDF файл с расписанием...")

    pdf_file = await asyncio.to_thread(generate_pdf)

    if pdf_file:
        file = FSInputFile(pdf_file)

        try:
            await message.answer_document(
                document=file,
                caption="📊 Расписание намазов на месяц"
            )
            # Удаляем файл после успешной отправки
            os.remove(pdf_file)
            logger = logging.getLogger(__name__)
            logger.info(f"PDF файл {pdf_file} удалён после отправки")
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"Ошибка отправки PDF: {e}")
            # Оставляем файл для отладки
            raise
    else:
        await message.answer("❌ Не удалось сгенерировать PDF")


@dp.message(Command("next"))
async def next_handler(message: Message):
    text = get_next_prayer()
    await message.answer(text, parse_mode="HTML")


@dp.message()
async def debug_handler(message: Message):
    """Обработчик всех остальных сообщений"""
    print(f"📨 Получено сообщение от {message.chat.id}: {message.text}")
    await message.answer(
        "❓ Неизвестная команда\n"
        "Используйте /help для списка команд"
    )


async def send_message(text: str):
    """Отправляет сообщение в указанный чат"""
    if not BOT_TOKEN:
        raise ValueError("❌ BOT_TOKEN не найден в .env")

    if not CHAT_ID:
        print("❌ CHAT_ID не задан")
        return

    try:
        bot = get_bot()
        await bot.send_message(chat_id=CHAT_ID, text=text, parse_mode="HTML")
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения: {e}")


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
            print("✅ Команды установлены")
            return
        except Exception as e:
            print(f"⚠️ Попытка {i+1} не удалась: {e}")
            await asyncio.sleep(2)


async def start_bot():
    """Запускает бота"""
    bot_instance = init_bot()
    await set_commands()
    print("🚀 Бот запущен и готов к работе")
    await dp.start_polling(bot_instance)