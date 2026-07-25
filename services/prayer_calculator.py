"""
Независимый offline-расчёт времени намаза (алгоритм Adhan / adhanpy).

Параметры по умолчанию соответствуют расчётам ДУМ РФ / umma.ru:
- угол Фаджр: 16.0°
- угол Иша: 15.0°
- мазхаб Аср: Ханафи
- правило высоких широт: TWILIGHT_ANGLE
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from adhanpy.calculation.CalculationParameters import CalculationParameters
from adhanpy.calculation.HighLatitudeRule import HighLatitudeRule
from adhanpy.calculation.Madhab import Madhab
from adhanpy.PrayerTimes import PrayerTimes
from timezonefinder import TimezoneFinder

# Инициализируем искатель часовых поясов один раз
_tf = TimezoneFinder()


def get_timezone_by_coordinates(lat: float, lon: float) -> Optional[str]:
    """Определяет IANA-название часового пояса по координатам."""
    return _tf.timezone_at(lng=lon, lat=lat)


def get_prayer_times(
    lat: float,
    lon: float,
    tz_name: str,
    target_date: Optional[date] = None,
    use_hanafi: bool = True,
    fajr_angle: float = 16.0,
    isha_angle: float = 15.0,
) -> dict[str, str]:
    """
    Рассчитывает местное время намаза для координат и даты.

    Returns:
        Словарь с ключами Fajr, Sunrise, Dhuhr, Asr, Maghrib, Isha (формат HH:MM).
    """
    if target_date is None:
        target_date = date.today()

    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:
        raise ValueError(f"Некорректный часовой пояс: {tz_name}") from exc

    params = CalculationParameters(fajr_angle=fajr_angle, isha_angle=isha_angle)
    params.madhab = Madhab.HANAFI if use_hanafi else Madhab.SHAFI
    # TWILIGHT_ANGLE = angle-based правило для белых ночей (северные широты)
    params.high_latitude_rule = HighLatitudeRule.TWILIGHT_ANGLE

    # adhanpy 1.0.x принимает (lat, lon) и datetime
    prayer_date = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        tzinfo=tz,
    )
    prayer_times = PrayerTimes(
        (lat, lon),
        prayer_date,
        calculation_parameters=params,
        time_zone=tz,
    )

    return {
        "Fajr": prayer_times.fajr.strftime("%H:%M"),
        "Sunrise": prayer_times.sunrise.strftime("%H:%M"),
        "Dhuhr": prayer_times.dhuhr.strftime("%H:%M"),
        "Asr": prayer_times.asr.strftime("%H:%M"),
        "Maghrib": prayer_times.maghrib.strftime("%H:%M"),
        "Isha": prayer_times.isha.strftime("%H:%M"),
    }
