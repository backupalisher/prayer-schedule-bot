import asyncio
import sys
import signal
from scheduler.scheduler import start_scheduler, schedule_notifications
from bot.bot import start_bot
from db.database import init_db
from services.prayer_service import get_today_prayers
from parser.parser import parse_and_save
from config import USE_TELEGRAM
from services.monitor import start_monitoring, stop_monitoring, get_monitor_status


async def main():
    """Главная функция"""
    print("🕌 Запуск бота расписания намазов...")

    # Инициализируем базу данных
    init_db()
    print("✅ База данных инициализирована")

    # Парсим расписание при запуске (если нужно)
    print("📡 Парсинг расписания...")
    if parse_and_save():
        print("✅ Расписание успешно загружено")
    else:
        print("⚠️ Не удалось загрузить расписание, используются существующие данные")

    # Планируем уведомления на сегодня
    print("📅 Планирование уведомлений...")
    schedule_notifications()

    # Проверяем сегодняшнее расписание
    print("\n📋 Сегодняшнее расписание:")
    print(get_today_prayers())
    print()

    # Запускаем планировщик
    start_scheduler()

    # Запускаем мониторинг состояния бота
    print("📊 Запуск системы мониторинга состояния бота...")
    monitor = await start_monitoring(
        check_interval=300,  # Проверка каждые 5 минут
        max_failures=3      # 3 последовательных сбоя перед перезапуском
    )
    print("✅ Система мониторинга запущена")

    # Запускаем бота (только если USE_TELEGRAM=True)
    if USE_TELEGRAM:
        print("🤖 Запуск Telegram бота...")
        await start_bot()
    else:
        print("📡 Telegram бот отключен (USE_TELEGRAM=False)")
        print("⏳ Планировщик и мониторинг работают в фоновом режиме...")
        
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
                            print(f"📊 Мониторинг: ✅ Здоров (сбоев: {failures}/{max_failures})")
                        elif health == 'warning':
                            print(f"📊 Мониторинг: ⚠️ Предупреждение (сбоев: {failures}/{max_failures})")
                        elif health == 'critical':
                            print(f"📊 Мониторинг: 🚨 Критично (сбоев: {failures}/{max_failures})")
                            
        except KeyboardInterrupt:
            print("\n🛑 Программа остановлена пользователем")
        finally:
            # Останавливаем мониторинг при выходе
            print("🛑 Остановка системы мониторинга...")
            await stop_monitoring()


async def shutdown():
    """Корректное завершение работы"""
    print("\n🛑 Завершение работы...")
    
    # Останавливаем мониторинг
    try:
        await stop_monitoring()
    except:
        pass
    
    # Останавливаем планировщик
    try:
        from scheduler.scheduler import stop_scheduler
        stop_scheduler()
    except:
        pass
    
    print("👋 До свидания!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        asyncio.run(shutdown())
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Неожиданная ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)