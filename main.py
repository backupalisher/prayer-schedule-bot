import asyncio
import sys
import os
import logging
import fcntl
from scheduler.scheduler import start_scheduler, schedule_notifications, start_prayer_worker, stop_prayer_worker
from bot.bot import start_bot
from db.database import init_db
from services.notifier import get_today_prayers
from parser.parser import ensure_current_month_data
from settings import USE_TELEGRAM, MONITOR_ALERTS_ENABLED
from services.monitor import start_monitoring, stop_monitoring, get_monitor_status

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# PID-файл для защиты от повторного запуска
PID_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.pid")
_lock_file = None


def acquire_lock() -> bool:
    """
    Проверяет, не запущен ли уже экземпляр бота, используя flock.
    Возвращает True, если блокировка получена (можно запускаться).
    """
    global _lock_file
    try:
        _lock_file = open(PID_FILE, "w")
        fcntl.flock(_lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _lock_file.write(str(os.getpid()))
        _lock_file.flush()
        logger.info("🔒 Блокировка получена (PID: %s)", os.getpid())
        return True
    except (IOError, OSError):
        logger.error(
            "🚫 Бот уже запущен! PID-файл: %s. "
            "Если вы уверены, что бот не работает, удалите файл вручную: rm -f %s",
            PID_FILE, PID_FILE
        )
        return False


def release_lock():
    """Освобождает блокировку"""
    global _lock_file
    try:
        fcntl.flock(_lock_file, fcntl.LOCK_UN)
        _lock_file.close()
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
        logger.info("🔓 Блокировка освобождена")
    except Exception:
        pass


async def main():
    """Главная функция"""
    logger.info("🕌 Запуск бота расписания намазов...")

    # Проверяем, не запущен ли уже бот
    if not acquire_lock():
        logger.error("🚫 Выход: бот уже запущен в другом процессе")
        sys.exit(1)

    # Инициализируем базу данных
    init_db()
    logger.info("✅ База данных инициализирована")

    # Проверяем актуальность данных в БД и парсим при необходимости
    logger.info("📡 Проверка актуальности расписания...")
    if ensure_current_month_data():
        logger.info("✅ Расписание актуально")
    else:
        logger.warning("⚠️ Не удалось загрузить расписание, используются существующие данные")

    # Запускаем фоновый worker проверки времени намазов (основной механизм уведомлений)
    logger.info("🔄 Запуск фонового worker'а уведомлений...")
    await start_prayer_worker()

    # Планируем уведомления на сегодня (резервный механизм через APScheduler)
    logger.info("📅 Планирование уведомлений...")
    schedule_notifications()

    # Проверяем сегодняшнее расписание
    logger.info("\n📋 Сегодняшнее расписание:\n%s", get_today_prayers())

    # Запускаем планировщик
    start_scheduler()

    # Запускаем мониторинг состояния бота (только если включены алерты)
    if MONITOR_ALERTS_ENABLED:
        logger.info("📊 Запуск системы мониторинга состояния бота...")
        monitor = await start_monitoring(
            check_interval=300,  # Проверка каждые 5 минут
            max_failures=3      # 3 последовательных сбоя перед перезапуском
        )
        logger.info("✅ Система мониторинга запущена")
    else:
        logger.info("📊 Мониторинг состояния бота отключен (MONITOR_ALERTS_ENABLED=False)")

    # Запускаем бота (только если USE_TELEGRAM=True)
    if USE_TELEGRAM:
        logger.info("🤖 Запуск Telegram бота...")
        await start_bot()
    else:
        logger.info("📡 Telegram бот отключен (USE_TELEGRAM=False)")
        logger.info("⏳ Планировщик и мониторинг работают в фоновом режиме...")
        
        # Держим программу запущенной с периодической проверкой статуса
        try:
            check_counter = 0
            while True:
                await asyncio.sleep(60)  # Проверка каждую минуту
                check_counter += 1
                
                # Каждые 5 минут выводим статус мониторинга
                if check_counter % 5 == 0:
                    status = get_monitor_status()
                    if status:
                        health = status['health']
                        failures = status['failure_count']
                        max_failures = status['max_failures']
                        
                        if health == 'healthy':
                            logger.info("📊 Мониторинг: ✅ Здоров (сбоев: %s/%s)", failures, max_failures)
                        elif health == 'warning':
                            logger.warning("📊 Мониторинг: ⚠️ Предупреждение (сбоев: %s/%s)", failures, max_failures)
                        elif health == 'critical':
                            logger.error("📊 Мониторинг: 🚨 Критично (сбоев: %s/%s)", failures, max_failures)
                            
        except KeyboardInterrupt:
            logger.info("🛑 Программа остановлена пользователем")
        finally:
            # Останавливаем мониторинг при выходе
            logger.info("🛑 Остановка системы мониторинга...")
            await stop_monitoring()


async def shutdown():
    """Корректное завершение работы"""
    logger.info("🛑 Завершение работы...")
    
    # Останавливаем фоновый worker уведомлений
    try:
        await stop_prayer_worker()
    except Exception:
        pass
    
    # Останавливаем мониторинг
    try:
        await stop_monitoring()
    except Exception:
        pass
    
    # Останавливаем планировщик
    try:
        from scheduler.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    
    # Освобождаем блокировку
    release_lock()
    
    logger.info("👋 До свидания!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        asyncio.run(shutdown())
        sys.exit(0)
    except Exception as e:
        logger.error("❌ Неожиданная ошибка: %s", e)
        import traceback
        traceback.print_exc()
        sys.exit(1)
