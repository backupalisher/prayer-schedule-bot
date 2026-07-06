from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import pytz
import logging
from parser.parser import parse_and_save, ensure_current_month_data, parse_next_month
from services.notifier import prayer_time_worker
from db.database import get_connection
from db.crud import get_by_date, is_data_actual
import asyncio

# Настройка логирования
logger = logging.getLogger(__name__)

# Устанавливаем временную зону (Москва UTC+3)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)

# Ссылка на фоновую задачу проверки времени намазов
_prayer_worker_task = None


def schedule_notifications():
    """Проверяет наличие расписания на сегодня (уведомления отправляет prayer_time_worker)."""
    conn = None
    try:
        conn = get_connection()
        today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
        logger.info("📅 Проверка расписания на %s", today)

        row = get_by_date(conn, today)

        if not row:
            logger.warning("⚠️ Нет данных для %s, пробую загрузить через парсер...", today)
            if ensure_current_month_data():
                row = get_by_date(conn, today)
            if not row:
                logger.error("❌ Данные для %s отсутствуют", today)
                return

        prayers = {
            "Фаджр": row[2],
            "Шурук": row[3],
            "Зухр": row[4],
            "Аср": row[5],
            "Магриб": row[6],
            "Иша": row[7],
        }

        valid_count = 0
        for name, time_str in prayers.items():
            if time_str and ':' in time_str:
                valid_count += 1
                logger.info("   ✓ %s: %s", name, time_str)
            else:
                logger.warning("   ✗ %s: нет времени (%s)", name, time_str)

        logger.info(
            "✅ Расписание на %s: %s/6 намазов. "
            "Уведомления отправляет фоновый worker (без дублирования через cron).",
            today, valid_count
        )

    except Exception as e:
        logger.error("❌ Ошибка в schedule_notifications: %s: %s", type(e).__name__, e)
        import traceback
        traceback.print_exc()
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


async def start_prayer_worker():
    """Запускает фоновую задачу проверки времени намазов по БД"""
    global _prayer_worker_task
    
    # Останавливаем предыдущую задачу, если есть
    if _prayer_worker_task and not _prayer_worker_task.done():
        _prayer_worker_task.cancel()
        try:
            await _prayer_worker_task
        except asyncio.CancelledError:
            pass
    
    # Запускаем новую фоновую задачу
    _prayer_worker_task = asyncio.create_task(prayer_time_worker())
    logger.info("✅ Фоновый worker проверки времени намазов запущен")


async def stop_prayer_worker():
    """Останавливает фоновую задачу проверки времени намазов"""
    global _prayer_worker_task
    
    if _prayer_worker_task and not _prayer_worker_task.done():
        _prayer_worker_task.cancel()
        try:
            await _prayer_worker_task
        except asyncio.CancelledError:
            pass
        _prayer_worker_task = None
        logger.info("🛑 Фоновый worker проверки времени намазов остановлен")


def start_scheduler():
    """Запускает планировщик задач с улучшенной обработкой ошибок"""
    try:
        logger.info("🚀 Запуск планировщика задач...")
        
        # Проверяем, не запущен ли уже планировщик
        if scheduler.running:
            logger.warning("⚠️ Планировщик уже запущен, пропускаем повторный запуск")
            return
        
        # Парсинг расписания 1-го числа каждого месяца в 00:30
        scheduler.add_job(
            parse_and_save,
            "cron",
            day=1,
            hour=0,
            minute=30,
            id="parse_schedule",
            replace_existing=True,
            misfire_grace_time=3600  # 1 час на выполнение пропущенной задачи
        )
        logger.info("📅 Задача парсинга расписания запланирована (1-е число месяца, 00:30)")

        # Парсинг следующего месяца 1-го числа в 01:00 (после парсинга текущего)
        scheduler.add_job(
            parse_next_month,
            "cron",
            day=1,
            hour=1,
            minute=0,
            id="parse_next_month",
            replace_existing=True,
            misfire_grace_time=3600
        )
        logger.info("📅 Задача парсинга следующего месяца запланирована (1-е число, 01:00)")

        # Планирование уведомлений каждый день в 00:05
        scheduler.add_job(
            schedule_notifications,
            "cron",
            hour=0,
            minute=5,
            id="schedule_daily",
            replace_existing=True,
            misfire_grace_time=3600  # 1 час на выполнение пропущенной задачи
        )
        logger.info("📅 Ежедневная задача планирования уведомлений запланирована (00:05)")

        # Дополнительная проверка в 23:55 на случай сбоя
        scheduler.add_job(
            schedule_notifications,
            "cron",
            hour=23,
            minute=55,
            id="schedule_evening",
            replace_existing=True,
            misfire_grace_time=3600  # 1 час на выполнение пропущенной задачи
        )
        logger.info("📅 Вечерняя проверка планирования запланирована (23:55)")

        # Немедленное планирование уведомлений при запуске
        logger.info("🔄 Немедленное планирование уведомлений...")
        scheduler.add_job(
            schedule_notifications,
            "date",
            run_date=datetime.now(MOSCOW_TZ),
            id="schedule_immediate",
            replace_existing=True
        )

        # Запускаем планировщик
        scheduler.start()
        logger.info("✅ Планировщик задач успешно запущен")
        
        # Логируем состояние планировщика
        logger.info("📊 Состояние планировщика: %s", 'работает' if scheduler.running else 'остановлен')
        jobs = scheduler.get_jobs()
        logger.info("📊 Всего запланированных задач: %s", len(jobs))
        
        # Выводим информацию о следующих запусках
        for job in jobs[:3]:  # Показываем первые 3 задачи
            job_id = getattr(job, 'id', 'unknown')
            next_run = getattr(job, 'next_run_time', None)
            if next_run:
                next_run_local = next_run.astimezone(MOSCOW_TZ)
                logger.info("   - %s: следующий запуск %s МСК", job_id, next_run_local.strftime('%Y-%m-%d %H:%M:%S'))

    except Exception as e:
        logger.error("❌ Критическая ошибка запуска планировщика: %s: %s", type(e).__name__, e)
        import traceback
        traceback.print_exc()
        raise


def stop_scheduler():
    """Останавливает планировщик"""
    scheduler.shutdown()
    logger.info("🛑 Планировщик остановлен")
