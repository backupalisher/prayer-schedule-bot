"""
Мазхабы для расчёта Аср.

Астрономически для длины тени:
- ханафитский → тень × 2
- маликитский / шафиитский / ханбалитский → тень × 1 (Standard)

Все четыре доступны пользователю для явного выбора.
"""

from __future__ import annotations

from typing import Any, Optional

from adhanpy.calculation.Madhab import Madhab

MADHAB_HANAFI = "hanafi"
MADHAB_MALIKI = "maliki"
MADHAB_SHAFI = "shafi"
MADHAB_HANBALI = "hanbali"

MADHAB_ORDER: tuple[str, ...] = (
    MADHAB_HANAFI,
    MADHAB_MALIKI,
    MADHAB_SHAFI,
    MADHAB_HANBALI,
)

MADHAB_META: dict[str, dict[str, str]] = {
    MADHAB_HANAFI: {
        "label": "Ханафитский",
        "short": "Ханафи",
        "asr_rule": "тень × 2",
        "description": "Аср, когда тень = 2 длины предмета",
    },
    MADHAB_MALIKI: {
        "label": "Маликитский",
        "short": "Малики",
        "asr_rule": "тень × 1",
        "description": "Аср, когда тень = 1 длина предмета",
    },
    MADHAB_SHAFI: {
        "label": "Шафиитский",
        "short": "Шафии",
        "asr_rule": "тень × 1",
        "description": "Аср, когда тень = 1 длина предмета",
    },
    MADHAB_HANBALI: {
        "label": "Ханбалитский",
        "short": "Ханбали",
        "asr_rule": "тень × 1",
        "description": "Аср, когда тень = 1 длина предмета",
    },
}


def normalize_madhab(value: Optional[str], use_hanafi_fallback: Optional[bool] = None) -> str:
    """Нормализует код мазхаба; при отсутствии — fallback из use_hanafi."""
    if value:
        key = str(value).strip().lower()
        if key in MADHAB_META:
            return key
        # синонимы
        aliases = {
            "hanafi": MADHAB_HANAFI,
            "hanafiyya": MADHAB_HANAFI,
            "maliki": MADHAB_MALIKI,
            "malik": MADHAB_MALIKI,
            "shafi": MADHAB_SHAFI,
            "shafii": MADHAB_SHAFI,
            "shaafi": MADHAB_SHAFI,
            "hanbali": MADHAB_HANBALI,
            "hanbal": MADHAB_HANBALI,
        }
        if key in aliases:
            return aliases[key]

    if use_hanafi_fallback is None:
        return MADHAB_HANAFI
    return MADHAB_HANAFI if use_hanafi_fallback else MADHAB_SHAFI


def madhab_label(madhab: str, *, detailed: bool = True) -> str:
    """Человекочитаемое название мазхаба."""
    key = normalize_madhab(madhab)
    meta = MADHAB_META[key]
    if detailed:
        return f"{meta['label']} ({meta['asr_rule']})"
    return meta["label"]


def madhab_uses_hanafi_asr(madhab: str) -> bool:
    """True, если для Аср используется правило тени × 2."""
    return normalize_madhab(madhab) == MADHAB_HANAFI


def madhab_to_adhan(madhab: str) -> Madhab:
    """Маппинг в enum adhanpy (только HANAFI / SHAFI = Standard)."""
    if madhab_uses_hanafi_asr(madhab):
        return Madhab.HANAFI
    return Madhab.SHAFI


def resolve_user_madhab(user: Any) -> str:
    """Достаёт код мазхаба из записи пользователя (с совместимостью)."""
    if user is None:
        return MADHAB_HANAFI

    keys = user.keys() if hasattr(user, "keys") else []
    madhab_value = user["madhab"] if "madhab" in keys else None
    use_hanafi = bool(user["use_hanafi"]) if "use_hanafi" in keys else None
    return normalize_madhab(madhab_value, use_hanafi_fallback=use_hanafi)
