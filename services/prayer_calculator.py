"""
Независимый offline-расчёт времени намаза (алгоритм Adhan / adhanpy).

Автовыбор метода по локации:
- Саудовская Аравия / Мекка → Umm al-Qura (официальный)
- Россия / СНГ (типичные TZ) → ДУМ РФ (Fajr 16°, Isha 15°, Ханафи)
- Египет → Egyptian
- иначе → Muslim World League
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from adhanpy.calculation.CalculationMethod import CalculationMethod
from adhanpy.calculation.CalculationParameters import CalculationParameters
from adhanpy.calculation.HighLatitudeRule import HighLatitudeRule
from adhanpy.PrayerTimes import PrayerTimes
from timezonefinder import TimezoneFinder

from services.madhab import (
    MADHAB_HANAFI,
    MADHAB_SHAFI,
    madhab_to_adhan,
    madhab_uses_hanafi_asr,
    normalize_madhab,
)

_tf = TimezoneFinder()

RUSSIA_TIMEZONES = {
    "Europe/Kaliningrad",
    "Europe/Moscow",
    "Europe/Samara",
    "Europe/Volgograd",
    "Europe/Astrakhan",
    "Europe/Saratov",
    "Europe/Ulyanovsk",
    "Europe/Kirov",
    "Asia/Yekaterinburg",
    "Asia/Omsk",
    "Asia/Novosibirsk",
    "Asia/Barnaul",
    "Asia/Tomsk",
    "Asia/Novokuznetsk",
    "Asia/Krasnoyarsk",
    "Asia/Irkutsk",
    "Asia/Chita",
    "Asia/Yakutsk",
    "Asia/Khandyga",
    "Asia/Vladivostok",
    "Asia/Ust-Nera",
    "Asia/Magadan",
    "Asia/Sakhalin",
    "Asia/Srednekolymsk",
    "Asia/Kamchatka",
    "Asia/Anadyr",
}

CIS_TIMEZONES = {
    "Asia/Almaty",
    "Asia/Qyzylorda",
    "Asia/Aqtobe",
    "Asia/Aqtau",
    "Asia/Atyrau",
    "Asia/Oral",
    "Asia/Tashkent",
    "Asia/Samarkand",
    "Asia/Bishkek",
    "Asia/Dushanbe",
    "Asia/Ashgabat",
    "Asia/Baku",
    "Asia/Yerevan",
    "Asia/Tbilisi",
    "Europe/Minsk",
    "Europe/Kyiv",
    "Europe/Chisinau",
}


@dataclass(frozen=True)
class CalculationProfile:
    """Профиль расчёта намаза для локации пользователя."""

    method: str
    default_madhab: str
    fajr_angle: float
    isha_angle: float
    label: str

    @property
    def use_hanafi(self) -> bool:
        """Обратная совместимость: ханафитское правило Аср."""
        return madhab_uses_hanafi_asr(self.default_madhab)


def get_timezone_by_coordinates(lat: float, lon: float) -> Optional[str]:
    """Определяет IANA-название часового пояса по координатам."""
    return _tf.timezone_at(lng=lon, lat=lat)


def _is_saudi_arabia(lat: float, lon: float, tz_name: str) -> bool:
    if tz_name == "Asia/Riyadh":
        return True
    return 16.0 <= lat <= 32.5 and 34.5 <= lon <= 56.0


def detect_calculation_profile(
    lat: float,
    lon: float,
    tz_name: str,
) -> CalculationProfile:
    """
    Подбирает метод расчёта по координатам/TZ для совпадения с местными стандартами.
    """
    if _is_saudi_arabia(lat, lon, tz_name):
        return CalculationProfile(
            method="umm_al_qura",
            default_madhab=MADHAB_SHAFI,
            fajr_angle=18.5,
            isha_angle=0.0,
            label="Umm al-Qura (Саудовская Аравия)",
        )

    if tz_name in {"Africa/Cairo", "Egypt"} or (
        22.0 <= lat <= 32.0 and 24.0 <= lon <= 37.0 and tz_name.startswith("Africa/")
    ):
        return CalculationProfile(
            method="egyptian",
            default_madhab=MADHAB_SHAFI,
            fajr_angle=19.5,
            isha_angle=17.5,
            label="Egyptian General Authority",
        )

    if tz_name in RUSSIA_TIMEZONES or tz_name in CIS_TIMEZONES:
        return CalculationProfile(
            method="dum_rf",
            default_madhab=MADHAB_HANAFI,
            fajr_angle=16.0,
            isha_angle=15.0,
            label="ДУМ РФ (16°/15°)",
        )

    return CalculationProfile(
        method="muslim_world_league",
        default_madhab=MADHAB_SHAFI,
        fajr_angle=18.0,
        isha_angle=17.0,
        label="Muslim World League",
    )


def _build_parameters(
    method: str,
    madhab: str,
    fajr_angle: float,
    isha_angle: float,
) -> CalculationParameters:
    method_enum_map = {
        "umm_al_qura": CalculationMethod.UMM_AL_QURA,
        "muslim_world_league": CalculationMethod.MUSLIM_WORLD_LEAGUE,
        "egyptian": CalculationMethod.EGYPTIAN,
        "karachi": CalculationMethod.KARACHI,
        "north_america": CalculationMethod.NORTH_AMERICA,
        "dubai": CalculationMethod.DUBAI,
        "kuwait": CalculationMethod.KUWAIT,
        "qatar": CalculationMethod.QATAR,
        "singapore": CalculationMethod.SINGAPORE,
        "uoif": CalculationMethod.UOIF,
    }

    if method in method_enum_map:
        params = CalculationParameters(method=method_enum_map[method])
    else:
        # dum_rf / custom — явные углы
        params = CalculationParameters(fajr_angle=fajr_angle, isha_angle=isha_angle)

    params.madhab = madhab_to_adhan(madhab)
    params.high_latitude_rule = HighLatitudeRule.TWILIGHT_ANGLE
    return params


def get_prayer_times(
    lat: float,
    lon: float,
    tz_name: str,
    target_date: Optional[date] = None,
    use_hanafi: bool = True,
    fajr_angle: float = 16.0,
    isha_angle: float = 15.0,
    method: str = "dum_rf",
    madhab: Optional[str] = None,
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

    resolved_madhab = normalize_madhab(madhab, use_hanafi_fallback=use_hanafi)
    params = _build_parameters(method, resolved_madhab, fajr_angle, isha_angle)
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
