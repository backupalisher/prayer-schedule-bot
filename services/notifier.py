import asyncio
import time
from config import USE_TELEGRAM, BOT_TOKEN
from bot.bot import get_bot
from db.database import get_connection
from db.crud import get_all_users


async def send_telegram_message(text, chat_id=None, max_retries=3, timeout=10):
    """Отправляет сообщение в Telegram с повторными попытками и таймаутами"""
    if not USE_TELEGRAM or not BOT_TOKEN:
        print(f"🔔 {text}")
        return False

    # Если chat_id не указан, используем старый подход (для обратной совместимости)
    if chat_id is None:
        from config import CHAT_ID
        if not CHAT_ID:
            print(f"🔔 {text}")
            return False
        chat_id = CHAT_ID

    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Используем общий экземпляр бота
            bot = get_bot()
            
            # Отправляем сообщение с таймаутом
            await asyncio.wait_for(
                bot.send_message(chat_id=chat_id, text=text),
                timeout=timeout
            )
            
            print(f"✅ Сообщение отправлено в Telegram (chat_id: {chat_id}): {text[:50]}...")
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
    print(f"❌ Не удалось отправить сообщение в Telegram (chat_id: {chat_id}) после {max_retries} попыток")
    print(f"   Последняя ошибка: {last_error}")
    print(f"   Текст сообщения: {text}")
    return False


async def send_telegram_message_to_all(text, max_retries=3, timeout=10):
    """Отправляет сообщение всем пользователям из БД"""
    if not USE_TELEGRAM or not BOT_TOKEN:
        print(f"🔔 {text}")
        return 0
    
    # Получаем всех пользователей из БД
    conn = get_connection()
    users = get_all_users(conn)
    conn.close()
    
    if not users:
        print("⚠️ Нет пользователей в БД для отправки уведомлений")
        return 0
    
    print(f"📨 Отправка уведомления {len(users)} пользователям: {text[:50]}...")
    
    success_count = 0
    for user in users:
        chat_id = user[1]  # chat_id находится во втором столбце
        try:
            success = await send_telegram_message(text, chat_id=chat_id, max_retries=max_retries, timeout=timeout)
            if success:
                success_count += 1
        except Exception as e:
            print(f"❌ Ошибка при отправке пользователю {chat_id}: {e}")
    
    print(f"📊 Итог: отправлено {success_count} из {len(users)} пользователям")
    return success_count


async def notify_async(prayer_name):
    """Асинхронное уведомление о времени намаза"""
    message = f"🕌 Время намаза: {prayer_name} \nСпешите к спасению!"
    print(f"🔔 {message}")
    
    try:
        success_count = await send_telegram_message_to_all(message)
        if success_count > 0:
            print(f"✅ Уведомление '{prayer_name}' успешно отправлено {success_count} пользователям")
            return True
        else:
            print(f"❌ Не удалось отправить уведомление '{prayer_name}' ни одному пользователю")
            return False
    except Exception as e:
        print(f"❌ Критическая ошибка при отправке уведомления '{prayer_name}': {e}")
        return False


def notify(prayer_name):
    """Синхронная обертка для уведомления (для использования из планировщика)"""
    message = f"🕌 Время намаза: {prayer_name} \nСпешите к спасению!"
    print(f"🔔 {message}")
    
    if not USE_TELEGRAM or not BOT_TOKEN:
        print("⚠️ Telegram отключен в настройках")
        return 0
    
    # Для синхронного вызова создаем новый event loop
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success_count = loop.run_until_complete(send_telegram_message_to_all(message))
        
        if success_count > 0:
            print(f"✅ Уведомление '{prayer_name}' успешно отправлено {success_count} пользователям (синхронно)")
        else:
            print(f"❌ Не удалось отправить уведомление '{prayer_name}' ни одному пользователю (синхронно)")
        
        return success_count
    except RuntimeError as e:
        if "There is no current event loop" in str(e):
            # Пытаемся использовать существующий event loop
            try:
                loop = asyncio.get_event_loop()
                success_count = loop.run_until_complete(send_telegram_message_to_all(message))
                print(f"✅ Использован существующий event loop для '{prayer_name}'")
                return success_count
            except:
                pass
        print(f"❌ Ошибка event loop для '{prayer_name}': {e}")
        return 0
    except Exception as e:
        print(f"❌ Критическая ошибка при отправке уведомления '{prayer_name}': {e}")
        return 0
    finally:
        try:
            if 'loop' in locals() and not loop.is_closed():
                loop.close()
        except:
            pass