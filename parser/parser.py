"""
Ежемесячный пересчёт персональных расписаний намазов.

Публичный API сохранён для совместимости с main/scheduler:
- parse_and_save
- ensure_current_month_data
- parse_next_month
"""

from __future__ import annotations

import logging

from services.user_schedule import recalculate_all_users

logger = logging.getLogger(__name__)


def parse_and_save(target_year: int | None = None, target_month: int | None = None) -> bool:
    """
    Пересчитывает персональные расписания всех пользователей с геолокацией.

    Аргументы target_year/target_month сохранены для совместимости API,
    фактический расчёт идёт по локальному календарю каждого пользователя.
    """
    if target_year is not None or target_month is not None:
        logger.info(
            "📅 Запрошен пересчёт (target=%s/%s) — выполняю для всех пользователей",
            target_month,
            target_year,
        )
    else:
        logger.info("📅 Offline-пересчёт персональных расписаний для всех пользователей")

    count = recalculate_all_users(months_ahead=1)
    return count > 0


def ensure_current_month_data() -> bool:
    """
    При старте пересчитывает расписания всех пользователей с геолокацией.
    Если пользователей ещё нет — это не ошибка.
    """
    logger.info("🔄 Проверка/обновление персональных расписаний...")
    recalculate_all_users(months_ahead=1)
    return True


def parse_next_month() -> bool:
    """Дополнительный пересчёт текущего и следующего месяца для всех пользователей."""
    logger.info("🔄 Offline-пересчёт текущего и следующего месяца для всех пользователей")
    count = recalculate_all_users(months_ahead=1)
    return count > 0
