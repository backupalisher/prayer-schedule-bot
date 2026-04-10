import asyncio
import time
from config import USE_TELEGRAM, BOT_TOKEN, CHAT_ID
from bot.bot import get_bot


async def send_telegram_message(text, max_retries=3, timeout=10):
    """Отправляет сообщение в Telegram с повторными попытками и таймаутами"""
    if not USE_TELEGRAM or not BOT_TOKEN or not CHAT_ID:
        print(f"🔔 {text}")
        return

    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Используем общий экземпляр бота
            bot = get_bot()
            
            # Отправляем сообщение с таймаутом
            await asyncio.wait_for(
                bot.send_message(chat_id=CHAT_ID, text=text),
                timeout=timeout
            )
            
            print(f"✅ Сообщение отправлено в Telegram: {text[:50]}...")
            return True
            
        except asyncio.TimeoutError:
            last_error = f"Таймаут ({timeout} секунд) при отправке сообщения"
            print(f"⚠️ Попытка {attempt + 1}/{max_retries}: {last_error}")
            
        except Exception as e:
            last_error = f"{type(e).__name__}: {str(e)}"
            print(f"⚠️ Попытка {attempt + 1}/{max_retries}: {last_error}")
            
        # Экспоненциальная задержка между попытками
        if attempt < max_retries - 1:
            delay = 2 ** attempt  # 1, 2, 4 секунды
            print(f"⏳ Повтор через {delay} секунд...")
            await asyncio.sleep(delay)
    
    # Все попытки исчерпаны
    print(f"❌ Не удалось отправить сообщение в Telegram после {max_retries} попыток")
    print(f"   Последняя ошибка: {last_error}")
    print(f"   Текст сообщения: {text}")
    return False


async def notify_async(prayer_name):
    """Асинхронное уведомление о времени намаза"""
    message = f"🕌 Время намаза: {prayer_name} \nСпешите к спасению!"
    print(f"🔔 {message}")
    
    try:
        success = await send_telegram_message(message)
        if success:
            print(f"✅ Уведомление '{prayer_name}' успешно отправлено")
        else:
            print(f"❌ Не удалось отправить уведомление '{prayer_name}'")
        return success
    except Exception as e:
        print(f"❌ Критическая ошибка при отправке уведомления '{prayer_name}': {e}")
        return False


def notify(prayer_name):
    """Синхронная обертка для уведомления (для использования из планировщика)"""
    message = f"🕌 Время намаза: {prayer_name} \nСпешите к спасению!"
    print(f"🔔 {message}")
    
    if not USE_TELEGRAM or not BOT_TOKEN or not CHAT_ID:
        print("⚠️ Telegram отключен в настройках")
        return
    
    # Для синхронного вызова создаем новый event loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(send_telegram_message(message))
        
        if success:
            print(f"✅ Уведомление '{prayer_name}' успешно отправлено (синхронно)")
        else:
            print(f"❌ Не удалось отправить уведомление '{prayer_name}' (синхронно)")
        
        return success
    except RuntimeError as e:
        if "There is no current event loop" in str(e):
            # Пытаемся использовать существующий event loop
            try:
                loop = asyncio.get_event_loop()
                success = loop.run_until_complete(send_telegram_message(message))
                print(f"✅ Использован существующий event loop для '{prayer_name}'")
                return success
            except:
                pass
        print(f"❌ Ошибка event loop для '{prayer_name}': {e}")
        return False
    except Exception as e:
        print(f"❌ Критическая ошибка при отправке уведомления '{prayer_name}': {e}")
        return False
    finally:
        try:
            if 'loop' in locals() and not loop.is_closed():
                loop.close()
        except:
            pass