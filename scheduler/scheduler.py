from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import pytz
from parser.parser import parse_and_save
from services.notifier import notify
from db.database import get_connection
from db.crud import get_by_date
import asyncio

# Устанавливаем временную зону (Москва UTC+3)
MOSCOW_TZ = pytz.timezone('Europe/Moscow')
scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)


def schedule_notifications():
    """Планирует уведомления на сегодня с улучшенной обработкой ошибок"""
    conn = None
    try:
        conn = get_connection()
        today = datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")
        print(f"📅 Начинаю планирование уведомлений на {today}")
        
        row = get_by_date(conn, today)

        if not row:
            print(f"⚠️ Нет данных для {today}, уведомления не запланированы")
            # Попробуем загрузить данные, если их нет
            print("🔄 Попытка загрузить данные через парсер...")
            from parser.parser import parse_and_save
            if parse_and_save():
                print("✅ Данные успешно загружены, повторная попытка планирования...")
                row = get_by_date(conn, today)
                if not row:
                    print(f"❌ Данные для {today} все еще отсутствуют")
                    return
            else:
                print(f"❌ Не удалось загрузить данные для {today}")
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
                    print(f"🗑️ Удалена старая задача: {job_id}")
                except Exception as e:
                    print(f"⚠️ Не удалось удалить старую задачу {job_id}: {e}")

        for name, time_str in prayers.items():
            try:
                # Проверяем формат времени
                if not time_str or ':' not in time_str:
                    print(f"⚠️ Неверный формат времени для {name}: '{time_str}'")
                    failed_count += 1
                    continue

                # Валидация времени
                try:
                    hour_str, minute_str = time_str.split(":")
                    hour = int(hour_str)
                    minute = int(minute_str)
                    
                    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                        print(f"⚠️ Некорректное время для {name}: {time_str}")
                        failed_count += 1
                        continue
                except (ValueError, TypeError) as e:
                    print(f"⚠️ Не удалось распарсить время для {name}: '{time_str}' - {e}")
                    failed_count += 1
                    continue

                # Проверяем, не прошло ли уже время намаза
                now = datetime.now(MOSCOW_TZ)
                prayer_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                
                if prayer_time < now:
                    print(f"⏰ Время намаза '{name}' ({time_str}) уже прошло, пропускаем")
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
                print(f"📅 Запланировано уведомление для '{name}' в {time_str} (МСК), ID: {job_id}")
                
            except Exception as e:
                print(f"❌ Критическая ошибка планирования для '{name}': {type(e).__name__}: {e}")
                failed_count += 1

        if scheduled_count > 0:
            print(f"✅ Успешно запланировано {scheduled_count} уведомлений на {today}")
        else:
            print(f"⚠️ Не запланировано ни одного уведомления на {today}")
            
        if failed_count > 0:
            print(f"⚠️ Не удалось запланировать {failed_count} уведомлений")
            
        # Логируем все запланированные задачи
        jobs = scheduler.get_jobs()
        if jobs:
            print(f"📋 Всего активных задач в планировщике: {len(jobs)}")
            for job in jobs[:5]:  # Показываем первые 5 задач
                job_id = getattr(job, 'id', 'unknown')
                next_run = getattr(job, 'next_run_time', None)
                print(f"   - {job_id}: {next_run}")
        else:
            print("📋 В планировщике нет активных задач")

    except Exception as e:
        print(f"❌ Критическая ошибка в schedule_notifications: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass


def start_scheduler():
    """Запускает планировщик задач с улучшенной обработкой ошибок"""
    try:
        print("🚀 Запуск планировщика задач...")
        
        # Проверяем, не запущен ли уже планировщик
        if scheduler.running:
            print("⚠️ Планировщик уже запущен, пропускаем повторный запуск")
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
        print("📅 Задача парсинга расписания запланирована (1-е число месяца, 00:30)")

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
        print("📅 Ежедневная задача планирования уведомлений запланирована (00:05)")

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
        print("📅 Вечерняя проверка планирования запланирована (23:55)")

        # Немедленное планирование уведомлений при запуске
        print("🔄 Немедленное планирование уведомлений...")
        scheduler.add_job(
            schedule_notifications,
            "date",
            run_date=datetime.now(MOSCOW_TZ),
            id="schedule_immediate",
            replace_existing=True
        )

        # Запускаем планировщик
        scheduler.start()
        print("✅ Планировщик задач успешно запущен")
        
        # Логируем состояние планировщика
        print(f"📊 Состояние планировщика: {'работает' if scheduler.running else 'остановлен'}")
        jobs = scheduler.get_jobs()
        print(f"📊 Всего запланированных задач: {len(jobs)}")
        
        # Выводим информацию о следующих запусках
        for job in jobs[:3]:  # Показываем первые 3 задачи
            job_id = getattr(job, 'id', 'unknown')
            next_run = getattr(job, 'next_run_time', None)
            if next_run:
                next_run_local = next_run.astimezone(MOSCOW_TZ)
                print(f"   - {job_id}: следующий запуск {next_run_local.strftime('%Y-%m-%d %H:%M:%S')} МСК")

    except Exception as e:
        print(f"❌ Критическая ошибка запуска планировщика: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        raise


def stop_scheduler():
    """Останавливает планировщик"""
    scheduler.shutdown()
    print("🛑 Планировщик остановлен")