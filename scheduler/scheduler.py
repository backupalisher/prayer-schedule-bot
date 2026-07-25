from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime, timezone
import logging
from parser.parser import parse_and_save, ensure_current_month_data, parse_next_month
from services.notifier import prayer_time_worker
from db.database import get_connection
from db.crud import get_users_with_location, get_user_prayers_by_date
import asyncio
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# UTC: пользователи по всему миру, локальное время учитывается в worker'е
scheduler = AsyncIOScheduler(timezone=timezone.utc)

_prayer_worker_task = None


def schedule_notifications():
    """Проверяет наличие персональных расписаний у пользователей с геолокацией."""
    conn = None
    try:
        conn = get_connection()
        users = get_users_with_location(conn)
        logger.info("📅 Проверка персональных расписаний: пользователей=%s", len(users))

        if not users:
            logger.info("ℹ️ Нет пользователей с геолокацией — уведомления пока некому слать")
            return

        ready = 0
        for user in users:
            try:
                tz = ZoneInfo(user["timezone"])
            except Exception:
                continue
            today = datetime.now(tz).strftime("%Y-%m-%d")
            row = get_user_prayers_by_date(conn, user["chat_id"], today)
            if row:
                ready += 1
            else:
                logger.warning(
                    "⚠️ Нет расписания на %s для chat_id=%s",
                    today, user["chat_id"],
                )

        if ready < len(users):
            logger.info("🔄 Часть расписаний отсутствует — запускаю пересчёт...")
            ensure_current_month_data()

        logger.info(
            "✅ Готово расписаний: %s/%s. Уведомления отправляет per-user worker.",
            ready, len(users),
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
    """Запускает фоновую задачу персональных уведомлений."""
    global _prayer_worker_task

    if _prayer_worker_task and not _prayer_worker_task.done():
        _prayer_worker_task.cancel()
        try:
            await _prayer_worker_task
        except asyncio.CancelledError:
            pass

    _prayer_worker_task = asyncio.create_task(prayer_time_worker())
    logger.info("✅ Фоновый worker персональных уведомлений запущен")


async def stop_prayer_worker():
    """Останавливает фоновую задачу проверки времени намазов."""
    global _prayer_worker_task

    if _prayer_worker_task and not _prayer_worker_task.done():
        _prayer_worker_task.cancel()
        try:
            await _prayer_worker_task
        except asyncio.CancelledError:
            pass
        _prayer_worker_task = None
        logger.info("🛑 Фоновый worker персональных уведомлений остановлен")


def start_scheduler():
    """Запускает планировщик задач с улучшенной обработкой ошибок."""
    try:
        logger.info("🚀 Запуск планировщика задач...")

        if scheduler.running:
            logger.warning("⚠️ Планировщик уже запущен, пропускаем повторный запуск")
            return

        scheduler.add_job(
            parse_and_save,
            "cron",
            day=1,
            hour=0,
            minute=30,
            id="parse_schedule",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("📅 Пересчёт персональных расписаний: 1-е число, 00:30 UTC")

        scheduler.add_job(
            parse_next_month,
            "cron",
            day=1,
            hour=1,
            minute=0,
            id="parse_next_month",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("📅 Доп. пересчёт следующего месяца: 1-е число, 01:00 UTC")

        scheduler.add_job(
            schedule_notifications,
            "cron",
            hour=0,
            minute=5,
            id="schedule_daily",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("📅 Ежедневная проверка персональных расписаний: 00:05 UTC")

        scheduler.add_job(
            schedule_notifications,
            "cron",
            hour=12,
            minute=0,
            id="schedule_midday",
            replace_existing=True,
            misfire_grace_time=3600,
        )
        logger.info("📅 Дневная проверка персональных расписаний: 12:00 UTC")

        scheduler.add_job(
            schedule_notifications,
            "date",
            run_date=datetime.now(timezone.utc),
            id="schedule_immediate",
            replace_existing=True,
        )

        scheduler.start()
        logger.info("✅ Планировщик задач успешно запущен")

        jobs = scheduler.get_jobs()
        logger.info("📊 Всего запланированных задач: %s", len(jobs))
        for job in jobs[:3]:
            job_id = getattr(job, "id", "unknown")
            next_run = getattr(job, "next_run_time", None)
            if next_run:
                logger.info("   - %s: следующий запуск %s", job_id, next_run.isoformat())

    except Exception as e:
        logger.error("❌ Критическая ошибка запуска планировщика: %s: %s", type(e).__name__, e)
        import traceback
        traceback.print_exc()
        raise


def stop_scheduler():
    """Останавливает планировщик."""
    scheduler.shutdown()
    logger.info("🛑 Планировщик остановлен")
