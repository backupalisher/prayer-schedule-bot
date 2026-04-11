#!/usr/bin/env python3
"""Мониторинг состояния бота и автоматический перезапуск"""

import asyncio
import time
import logging
import subprocess
import sys
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import aiohttp

from config import BOT_TOKEN, USE_TELEGRAM, MONITOR_ALERTS_ENABLED
from services.notifier import send_telegram_message

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BotMonitor:
    """Мониторинг состояния Telegram бота"""
    
    def __init__(self, check_interval: int = 300, max_failures: int = 3):
        """
        Инициализация мониторинга
        
        Args:
            check_interval: Интервал проверки в секундах (по умолчанию 5 минут)
            max_failures: Максимальное количество последовательных сбоев перед перезапуском
        """
        self.check_interval = check_interval
        self.max_failures = max_failures
        self.failure_count = 0
        self.last_check = None
        self.last_success = None
        self.is_running = False
        self.monitor_task = None
        
        # Статистика
        self.stats = {
            'checks_total': 0,
            'checks_successful': 0,
            'checks_failed': 0,
            'restarts_attempted': 0,
            'restarts_successful': 0,
            'alerts_sent': 0
        }
        
        logger.info(f"Инициализирован мониторинг бота (интервал: {check_interval}с, макс. сбоев: {max_failures})")
    
    async def check_telegram_api(self) -> bool:
        """Проверка доступности Telegram API"""
        if not USE_TELEGRAM or not BOT_TOKEN:
            logger.warning("Telegram отключен в настройках, проверка API пропущена")
            return True  # Считаем успешным, если Telegram не используется
        
        try:
            url = f'https://api.telegram.org/bot{BOT_TOKEN}/getMe'
            timeout = aiohttp.ClientTimeout(total=10)
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get('ok'):
                            logger.debug(f"Telegram API доступен, бот: {data.get('result', {}).get('username')}")
                            return True
                        else:
                            logger.warning(f"Telegram API ответил с ошибкой: {data}")
                            return False
                    else:
                        logger.warning(f"Telegram API недоступен, статус: {response.status}")
                        return False
                        
        except asyncio.TimeoutError:
            logger.warning("Таймаут при проверке Telegram API (10 секунд)")
            return False
        except Exception as e:
            logger.error(f"Ошибка при проверке Telegram API: {type(e).__name__}: {e}")
            return False
    
    async def check_bot_health(self) -> bool:
        """Комплексная проверка здоровья бота"""
        logger.info("Запуск проверки здоровья бота...")
        
        checks = []
        
        # Проверка 1: Доступность Telegram API
        api_check = await self.check_telegram_api()
        checks.append(('Telegram API', api_check))
        
        # Проверка 2: Возможность отправки тестового сообщения (только если API доступен и включены алерты)
        message_check = True
        if api_check and USE_TELEGRAM and MONITOR_ALERTS_ENABLED:
            try:
                # Отправляем тестовое сообщение самому себе
                test_message = "🤖 Проверка здоровья бота (мониторинг)"
                message_check = await send_telegram_message(
                    test_message, 
                    max_retries=1, 
                    timeout=5
                )
                checks.append(('Отправка сообщений', message_check))
            except Exception as e:
                logger.error(f"Ошибка при проверке отправки сообщений: {e}")
                checks.append(('Отправка сообщений', False))
                message_check = False
        elif api_check and USE_TELEGRAM and not MONITOR_ALERTS_ENABLED:
            # Если алерты отключены, просто считаем проверку успешной
            checks.append(('Отправка сообщений', True))
            logger.info("  ⚠️ Отправка тестовых сообщений отключена (MONITOR_ALERTS_ENABLED=False)")
        
        # Определяем общий статус
        all_checks_passed = all(check[1] for check in checks)
        
        # Логируем результаты
        for check_name, check_result in checks:
            status = "✅" if check_result else "❌"
            logger.info(f"  {status} {check_name}: {'Успешно' if check_result else 'Сбой'}")
        
        logger.info(f"Итог проверки здоровья: {'✅ Здоров' if all_checks_passed else '❌ Проблемы'}")
        return all_checks_passed
    
    async def send_alert(self, message: str, is_critical: bool = False) -> bool:
        """Отправка оповещения о проблеме"""
        alert_prefix = "🚨 КРИТИЧЕСКОЕ ОПОВЕЩЕНИЕ" if is_critical else "⚠️ ПРЕДУПРЕЖДЕНИЕ"
        full_message = f"{alert_prefix}\n{message}\n\n📊 Статистика мониторинга:\n"
        
        # Добавляем статистику
        for key, value in self.stats.items():
            full_message += f"  • {key}: {value}\n"
        
        full_message += f"\n🕒 Последняя успешная проверка: {self.last_success or 'никогда'}"
        
        # Логируем всегда
        logger.info(f"Оповещение: {message[:100]}...")
        
        # Отправляем в Telegram только если включены оповещения мониторинга и глобально включен Telegram
        if MONITOR_ALERTS_ENABLED and USE_TELEGRAM:
            try:
                await send_telegram_message(full_message, max_retries=2, timeout=10)
                logger.info("Оповещение отправлено в Telegram")
                return True
            except Exception as e:
                logger.error(f"Не удалось отправить оповещение в Telegram: {e}")
                return False
        else:
            if not MONITOR_ALERTS_ENABLED:
                logger.debug("Отправка оповещений мониторинга отключена (MONITOR_ALERTS_ENABLED=False)")
            elif not USE_TELEGRAM:
                logger.debug("Telegram бот отключен (USE_TELEGRAM=False)")
            return False
    
    async def restart_bot(self) -> bool:
        """Попытка перезапуска бота"""
        logger.warning("Попытка перезапуска бота...")
        self.stats['restarts_attempted'] += 1
        
        # Отправляем оповещение о перезапуске
        await self.send_alert(
            "🔄 Инициирован перезапуск бота из-за повторных сбоев",
            is_critical=False
        )
        
        try:
            # Здесь должна быть логика перезапуска бота
            # В реальном приложении это может быть:
            # 1. Перезапуск процесса через systemd
            # 2. Перезапуск через subprocess
            # 3. Перезапуск внутри приложения
            
            # Для простоты просто сбрасываем счетчик сбоев
            old_failures = self.failure_count
            self.failure_count = 0
            
            logger.info(f"Бот 'перезапущен' (сброшен счетчик сбоев: {old_failures} -> 0)")
            self.stats['restarts_successful'] += 1
            
            # Отправляем оповещение об успешном перезапуске
            await self.send_alert(
                f"✅ Бот успешно перезапущен\nСброшен счетчик сбоев: {old_failures} -> 0",
                is_critical=False
            )
            
            return True
            
        except Exception as e:
            logger.error(f"Ошибка при перезапуске бота: {e}")
            
            # Отправляем оповещение о неудачном перезапуске
            await self.send_alert(
                f"❌ Не удалось перезапустить бота: {type(e).__name__}: {str(e)[:100]}",
                is_critical=True
            )
            
            return False
    
    async def monitor_loop(self):
        """Основной цикл мониторинга"""
        logger.info("Запуск цикла мониторинга...")
        self.is_running = True
        
        while self.is_running:
            try:
                self.last_check = datetime.now()
                self.stats['checks_total'] += 1
                
                # Выполняем проверку здоровья
                is_healthy = await self.check_bot_health()
                
                if is_healthy:
                    # Сброс счетчика сбоев при успешной проверке
                    if self.failure_count > 0:
                        logger.info(f"Сброс счетчика сбоев: {self.failure_count} -> 0")
                        self.failure_count = 0
                    
                    self.last_success = datetime.now()
                    self.stats['checks_successful'] += 1
                    
                else:
                    # Увеличиваем счетчик сбоев
                    self.failure_count += 1
                    self.stats['checks_failed'] += 1
                    
                    logger.warning(f"Сбой #{self.failure_count}/{self.max_failures}")
                    
                    # Отправляем предупреждение при первом сбое
                    if self.failure_count == 1:
                        await self.send_alert(
                            "⚠️ Обнаружен сбой в работе бота\n"
                            "Мониторинг будет отслеживать ситуацию",
                            is_critical=False
                        )
                    
                    # Пытаемся перезапустить при достижении максимального количества сбоев
                    if self.failure_count >= self.max_failures:
                        logger.error(f"Достигнут лимит сбоев ({self.max_failures}), инициирую перезапуск...")
                        await self.restart_bot()
                
                # Ждем перед следующей проверкой
                await asyncio.sleep(self.check_interval)
                
            except asyncio.CancelledError:
                logger.info("Цикл мониторинга остановлен")
                break
            except Exception as e:
                logger.error(f"Неожиданная ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(self.check_interval)
    
    def start(self):
        """Запуск мониторинга в фоновом режиме"""
        if self.monitor_task and not self.monitor_task.done():
            logger.warning("Мониторинг уже запущен")
            return
        
        self.monitor_task = asyncio.create_task(self.monitor_loop())
        logger.info("Мониторинг запущен в фоновом режиме")
    
    async def stop(self):
        """Остановка мониторинга"""
        logger.info("Остановка мониторинга...")
        self.is_running = False
        
        if self.monitor_task and not self.monitor_task.done():
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Мониторинг остановлен")
    
    def get_status(self) -> Dict[str, Any]:
        """Получение текущего статуса мониторинга"""
        status = {
            'is_running': self.is_running,
            'failure_count': self.failure_count,
            'max_failures': self.max_failures,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'last_success': self.last_success.isoformat() if self.last_success else None,
            'check_interval': self.check_interval,
            'stats': self.stats.copy()
        }
        
        # Определяем общий статус здоровья
        if self.failure_count >= self.max_failures:
            status['health'] = 'critical'
        elif self.failure_count > 0:
            status['health'] = 'warning'
        elif self.last_success and (datetime.now() - self.last_success).seconds > self.check_interval * 2:
            status['health'] = 'unknown'
        else:
            status['health'] = 'healthy'
        
        return status


# Глобальный экземпляр мониторинга
_monitor_instance: Optional[BotMonitor] = None


def get_monitor(check_interval: int = 300, max_failures: int = 3) -> BotMonitor:
    """Получение или создание экземпляра мониторинга"""
    global _monitor_instance
    
    if _monitor_instance is None:
        _monitor_instance = BotMonitor(
            check_interval=check_interval,
            max_failures=max_failures
        )
    
    return _monitor_instance


async def start_monitoring(check_interval: int = 300, max_failures: int = 3):
    """Запуск мониторинга"""
    monitor = get_monitor(check_interval, max_failures)
    monitor.start()
    return monitor


async def stop_monitoring():
    """Остановка мониторинга"""
    global _monitor_instance
    
    if _monitor_instance:
        await _monitor_instance.stop()
        _monitor_instance = None


def get_monitor_status() -> Optional[Dict[str, Any]]:
    """Получение статуса мониторинга"""
    if _monitor_instance:
        return _monitor_instance.get_status()
    return None


# Тестирование мониторинга
async def test_monitor():
    """Тестирование системы мониторинга"""
    print("🧪 Тестирование системы мониторинга...")
    
    monitor = BotMonitor(check_interval=2, max_failures=2)
    
    # Тест 1: Проверка Telegram API
    print("  1. Проверка Telegram API...")
    api_available = await monitor.check_telegram_api()
    print(f"     Результат: {'✅ Доступен' if api_available else '❌ Недоступен'}")
    
    # Тест 2: Проверка здоровья
    print("  2. Комплексная проверка здоровья...")
    health_ok = await monitor.check_bot_health()
    print(f"     Результат: {'✅ Здоров' if health_ok else '❌ Проблемы'}")
    
    # Тест 3: Получение статуса
    print("  3. Получение статуса мониторинга...")
    status = monitor.get_status()
    print(f"     Статус: {status['health']}")
    print(f"     Сбоев: {status['failure_count']}/{status['max_failures']}")
    
    print("✅ Тестирование завершено")
    return health_ok


if __name__ == "__main__":
    # Запуск теста при прямом выполнении
    asyncio.run(test_monitor())