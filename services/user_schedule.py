"""
Персональный offline-расчёт и сохранение расписания намазов для пользователя.
"""

from __future__ import annotations

import calendar
import logging
from datetime import date, datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from db.crud import (
    get_user_by_chat_id,
    get_user_prayers_by_date,
    get_users_with_location,
    upsert_user_prayer,
    update_user_location,
    user_has_location,
)
from db.database import get_connection
from services.prayer_calculator import (
    CalculationProfile,
    detect_calculation_profile,
    get_prayer_times,
    get_timezone_by_coordinates,
)

logger = logging.getLogger(__name__)


def _user_local_now(timezone_name: str) -> datetime:
    return datetime.now(ZoneInfo(timezone_name))


def save_location_and_recalculate(
    chat_id: str | int,
    latitude: float,
    longitude: float,
    username: Optional[str] = None,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
) -> tuple[bool, Optional[str], Optional[CalculationProfile], Optional[dict[str, str]]]:
    """
    Сохраняет геолокацию пользователя, подбирает метод и пересчитывает расписание.

    Returns:
        (ok, timezone, profile, today_times)
    """
    tz_name = get_timezone_by_coordinates(latitude, longitude)
    if not tz_name:
        return False, None, None, None

    profile = detect_calculation_profile(latitude, longitude, tz_name)
    conn = get_connection()
    try:
        saved = update_user_location(
            conn,
            chat_id=chat_id,
            latitude=latitude,
            longitude=longitude,
            timezone=tz_name,
            calculation_method=profile.method,
            use_hanafi=profile.use_hanafi,
            fajr_angle=profile.fajr_angle,
            isha_angle=profile.isha_angle,
            username=username,
            first_name=first_name,
            last_name=last_name,
        )
        if not saved:
            return False, tz_name, profile, None

        user = get_user_by_chat_id(conn, chat_id)
        ok = recalculate_user_schedule(conn, user, months_ahead=1)
        if not ok:
            return False, tz_name, profile, None

        local_today = _user_local_now(tz_name).strftime("%Y-%m-%d")
        row = get_user_prayers_by_date(conn, chat_id, local_today)
        today_times = None
        if row:
            today_times = {
                "Fajr": row["fajr"],
                "Sunrise": row["shurooq"],
                "Dhuhr": row["dhuhr"],
                "Asr": row["asr"],
                "Maghrib": row["maghrib"],
                "Isha": row["isha"],
            }
        return True, tz_name, profile, today_times
    finally:
        conn.close()


def recalculate_user_schedule(
    conn,
    user: Any,
    months_ahead: int = 1,
) -> bool:
    """
    Пересчитывает и сохраняет расписание пользователя на текущий и следующие месяцы.
    """
    if not user_has_location(user):
        logger.warning("⚠️ У пользователя %s нет геоданных для расчёта", user["chat_id"])
        return False

    lat = float(user["latitude"])
    lon = float(user["longitude"])
    tz_name = str(user["timezone"])
    method = str(user["calculation_method"] or "dum_rf")
    use_hanafi = bool(user["use_hanafi"])
    fajr_angle = float(user["fajr_angle"] if user["fajr_angle"] is not None else 16.0)
    isha_angle = float(user["isha_angle"] if user["isha_angle"] is not None else 15.0)

    local_now = _user_local_now(tz_name)
    year = local_now.year
    month = local_now.month

    total_saved = 0
    for offset in range(months_ahead + 1):
        y = year
        m = month + offset
        while m > 12:
            m -= 12
            y += 1
        saved = _calculate_month_for_user(
            conn=conn,
            chat_id=user["chat_id"],
            year=y,
            month=m,
            lat=lat,
            lon=lon,
            tz_name=tz_name,
            method=method,
            use_hanafi=use_hanafi,
            fajr_angle=fajr_angle,
            isha_angle=isha_angle,
        )
        total_saved += saved

    logger.info(
        "✅ Пересчёт для chat_id=%s: сохранено %s дней (method=%s, tz=%s)",
        user["chat_id"],
        total_saved,
        method,
        tz_name,
    )
    return total_saved > 0


def _calculate_month_for_user(
    conn,
    chat_id: str,
    year: int,
    month: int,
    lat: float,
    lon: float,
    tz_name: str,
    method: str,
    use_hanafi: bool,
    fajr_angle: float,
    isha_angle: float,
) -> int:
    days_in_month = calendar.monthrange(year, month)[1]
    saved = 0
    for day in range(1, days_in_month + 1):
        target = date(year, month, day)
        try:
            times = get_prayer_times(
                lat=lat,
                lon=lon,
                tz_name=tz_name,
                target_date=target,
                use_hanafi=use_hanafi,
                fajr_angle=fajr_angle,
                isha_angle=isha_angle,
                method=method,
            )
        except Exception as exc:
            logger.warning(
                "⚠️ Ошибка расчёта для chat_id=%s %s: %s",
                chat_id, target, exc,
            )
            continue

        row = (
            target.strftime("%Y-%m-%d"),
            times["Fajr"],
            times["Sunrise"],
            times["Dhuhr"],
            times["Asr"],
            times["Maghrib"],
            times["Isha"],
        )
        if upsert_user_prayer(conn, chat_id, row):
            saved += 1

    conn.commit()
    return saved


def recalculate_all_users(months_ahead: int = 1) -> int:
    """Пересчитывает расписание для всех пользователей с геолокацией."""
    conn = get_connection()
    try:
        users = get_users_with_location(conn)
        ok_count = 0
        for user in users:
            try:
                if recalculate_user_schedule(conn, user, months_ahead=months_ahead):
                    ok_count += 1
            except Exception as exc:
                logger.error(
                    "❌ Ошибка пересчёта для chat_id=%s: %s",
                    user["chat_id"], exc,
                )
        logger.info("✅ Пересчитано расписание для %s/%s пользователей", ok_count, len(users))
        return ok_count
    finally:
        conn.close()


def ensure_user_current_month(chat_id: str | int) -> bool:
    """Гарантирует наличие расписания текущего месяца для пользователя."""
    conn = get_connection()
    try:
        user = get_user_by_chat_id(conn, chat_id)
        if not user_has_location(user):
            return False
        return recalculate_user_schedule(conn, user, months_ahead=1)
    finally:
        conn.close()
