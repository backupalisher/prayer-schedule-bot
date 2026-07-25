"""
Заполнение расписания намазов offline-расчётом (adhanpy).

Публичный API сохранён для совместимости с main/scheduler:
- parse_and_save
- ensure_current_month_data
- parse_next_month
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime

from db.crud import insert_prayer, is_data_actual
from db.database import get_connection
from services.prayer_calculator import get_prayer_times, get_timezone_by_coordinates
from settings import (
    PRAYER_FAJR_ANGLE,
    PRAYER_ISHA_ANGLE,
    PRAYER_LATITUDE,
    PRAYER_LONGITUDE,
    PRAYER_TIMEZONE,
    PRAYER_USE_HANAFI,
)

logger = logging.getLogger(__name__)


def _resolve_timezone(lat: float, lon: float, fallback_tz: str) -> str:
    """Определяет часовой пояс по координатам или возвращает fallback."""
    detected = get_timezone_by_coordinates(lat, lon)
    if detected:
        return detected
    logger.warning(
        "⚠️ Не удалось определить часовой пояс по координатам (%.4f, %.4f), "
        "используем %s",
        lat,
        lon,
        fallback_tz,
    )
    return fallback_tz


def parse_and_save(target_year: int | None = None, target_month: int | None = None) -> bool:
    """
    Рассчитывает расписание намазов на месяц и сохраняет в БД.

    Args:
        target_year: Год (по умолчанию текущий).
        target_month: Месяц 1-12 (по умолчанию текущий).

    Returns:
        True, если хотя бы одна запись сохранена.
    """
    now = datetime.now()
    year = target_year if target_year is not None else now.year
    month = target_month if target_month is not None else now.month

    if not (1 <= month <= 12):
        logger.error("❌ Некорректный месяц: %s", month)
        return False

    lat = PRAYER_LATITUDE
    lon = PRAYER_LONGITUDE
    tz_name = _resolve_timezone(lat, lon, PRAYER_TIMEZONE)

    days_in_month = calendar.monthrange(year, month)[1]
    logger.info(
        "📅 Offline-расчёт расписания на %s/%s (lat=%.4f, lon=%.4f, tz=%s, "
        "hanafi=%s, fajr=%.1f°, isha=%.1f°)",
        month,
        year,
        lat,
        lon,
        tz_name,
        PRAYER_USE_HANAFI,
        PRAYER_FAJR_ANGLE,
        PRAYER_ISHA_ANGLE,
    )

    data: list[tuple[str, str, str, str, str, str, str]] = []
    for day in range(1, days_in_month + 1):
        target = date(year, month, day)
        try:
            times = get_prayer_times(
                lat=lat,
                lon=lon,
                tz_name=tz_name,
                target_date=target,
                use_hanafi=PRAYER_USE_HANAFI,
                fajr_angle=PRAYER_FAJR_ANGLE,
                isha_angle=PRAYER_ISHA_ANGLE,
            )
        except Exception as exc:
            logger.warning("⚠️ Не удалось рассчитать намазы для %s: %s", target, exc)
            continue

        data.append(
            (
                target.strftime("%Y-%m-%d"),
                times["Fajr"],
                times["Sunrise"],  # shurooq
                times["Dhuhr"],
                times["Asr"],
                times["Maghrib"],
                times["Isha"],
            )
        )

    if not data:
        logger.error("❌ Не удалось рассчитать ни одного дня для %s/%s", month, year)
        return False

    conn = get_connection()
    try:
        saved_count = 0
        month_updated = year * 100 + month
        for row in data:
            if insert_prayer(conn, row, month_updated=month_updated):
                saved_count += 1

        logger.info(
            "✅ Offline-расчёт записал %s из %s дней в БД (метка месяца: %s)",
            saved_count,
            len(data),
            month_updated,
        )
        return saved_count > 0
    finally:
        conn.close()


def ensure_current_month_data() -> bool:
    """
    Гарантирует актуальные данные текущего месяца в БД.

    Offline-расчёт быстрый, поэтому при старте всегда пересчитываем месяц:
    это безопасно обновляет старые записи (в т.ч. после отказа от парсинга umma.ru).
    """
    now = datetime.now()
    year = now.year
    month = now.month

    conn = get_connection()
    try:
        has_data = is_data_actual(conn, year, month)
    except Exception:
        has_data = False
    finally:
        conn.close()

    if has_data:
        logger.info("🔄 Обновляю offline-расчёт на %s/%s...", month, year)
    else:
        logger.info("🔄 Данные на %s/%s отсутствуют, запускаю offline-расчёт...", month, year)

    return parse_and_save(target_year=year, target_month=month)


def parse_next_month() -> bool:
    """Рассчитывает и сохраняет расписание на следующий месяц."""
    now = datetime.now()
    year = now.year
    month = now.month

    if month == 12:
        next_year = year + 1
        next_month = 1
    else:
        next_year = year
        next_month = month + 1

    logger.info("🔄 Offline-расчёт следующего месяца: %s/%s", next_month, next_year)
    return parse_and_save(target_year=next_year, target_month=next_month)
