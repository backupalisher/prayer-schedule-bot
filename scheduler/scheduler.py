from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import pytz
import logging
from parser.parser import parse_and_save, ensure_current_month_data, parse_next_month
from services.notifier import notify, prayer_time_worker
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
    """Планирует уведомления на сегодня с улучшенной обработкой ошибок"""
    conn = None
    try:
        conn = get_connection()
        today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
        logger.info("📅 Начинаю планирование уведомлений на %s", today)
        
        row = get_by_date(conn, today)

        if not row:
            logger.warning("⚠️ Нет данных для %s, уведомления не запланированы", today)
            # Попробуем загрузить данные, если их нет
            logger.info("🔄 Попытка загрузить данные через парсер...")
            if ensure_current_month_data():
                logger.info("✅ Данные успешно загружены, повторная попытка планирования...")
                row = get_by_date(conn, today)
                if not row:
                    logger.error("❌ Данные для %s все еще отсутствуют", today)
                    return
            else:
                logger.error("❌ Не удалось загрузить данные для %s", today)
                return

        # Используем правильные индексы (совместимо с prayer_service.py)
        # row[0]=id, row[1]=date, row[2]=fajr, row[3]=shurooq, 
        # row[4]=dhuhr, row[5]=asr, row[6]=maghrib, row[7]=isha
        # Планируем все 6 намазов
        prayers = {
            "Фаджр": row[2],    # fajr
            "Шурук": row[3],    # shurooq
            "Зухр": row[4],     # dhuhr
            "Аср": row[5],      # asr
            "Магриб": row[6],   # maghrib
            "Иша": row[7],      # isha
        }

        scheduled_count = 0
        failed_count = 0
        
        # Удаляем старые задачи для сегодняшнего дня
        for job in scheduler.get_jobs():
            job_id = getattr(job, 'id', None)
            if job_id and isinstance(job_id, str) and job_id.startswith(f"prayer_") and today in job_id:
                try:
                    scheduler.remove_job(job_id)
                    logger.info("🗑️ Удалена старая задача: %s", job_id)
                except Exception as e:
                    logger.warning("⚠️ Не удалось удалить старую задачу %s: %s", job_id, e)

        for name, time_str in prayers.items():
            try:
                # Проверяем формат времени
                if not time_str or ':' not in time_str:
                    logger.warning("⚠️ Неверный формат времени для %s: '%s'", name, time_str)
                    failed_count += 1
                    continue

                # Валидация времени
                try:
                    hour_str, minute_str = time_str.split(":")
                    hour = int(hour_str)
                    minute = int(minute_str)
                    
                    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                        logger.warning("⚠️ Некорректное время для %s: %s", name, time_str)
                        failed_count += 1
                        continue
                except (ValueError, TypeError) as e:
                    logger.warning("⚠️ Не удалось распарсить время для %s: '%s' - %s", name, time_str, e)
                    failed_count += 1
                    continue

                # Проверяем, не прошло ли уже время намаза
                now = datetime.now(MOSCOW_TZ)
                prayer_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                if prayer_time < now:
                    logger.info("⏰ Время намаза '%s' (%s) уже прошло, пропускаем", name, time_str)
                    continue

                # Планируем уведомление с учетом временной зоны
                job_id = f"prayer_{name}_{today}"
                scheduler.add_job(
                    notify,
                    "cron",
                    hour=hour,
                    minute=minute,
                    args=[name],
                    id=job_id,
                    replace_existing=True,
                    timezone=MOSCOW_TZ,
                    misfire_grace_time=300  # 5 минут на выполнение пропущенной задачи
                )
                scheduled_count += 1
                logger.info("📅 Запланировано уведомление для '%s' в %s (МСК), ID: %s", name, time_str, job_id)
                
            except Exception as e:
                logger.error("❌ Критическая ошибка планирования для '%s': %s: %s", name, type(e).__name__, e)
                failed_count += 1

        if scheduled_count > 0:
            logger.info("✅ Успешно запланировано %s уведомлений на %s", scheduled_count, today)
        else:
            logger.warning("⚠️ Не запланировано ни одного уведомления на %s", today)
            
        if failed_count > 0:
            logger.warning("⚠️ Не удалось запланировать %s уведомлений", failed_count)
            
        # Логируем все запланированные задачи
        jobs = scheduler.get_jobs()
        if jobs:
            logger.info("📋 Всего активных задач в планировщике: %s", len(jobs))
            for job in jobs[:5]:  # Показываем первые 5 задач
                job_id = getattr(job, 'id', 'unknown')
                next_run = getattr(job, 'next_run_time', None)
                logger.info("   - %s: %s", job_id, next_run)
        else:
            logger.info("📋 В планировщике нет активных задач")

    except Exception as e:
        logger.error("❌ Критическая ошибка в schedule_notifications: %s: %s", type(e).__name__, e)
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
