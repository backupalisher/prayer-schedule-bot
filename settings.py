from pydantic_settings import BaseSettings
from typing import Optional


class PDFSettings(BaseSettings):
    """Настройки генерации PDF-календаря"""
    pdf_output_dir: str = "."

    pdf_font_regular: str = "assets/fonts/Inter-Regular.ttf"
    pdf_font_bold: str = "assets/fonts/Inter-Bold.ttf"
    pdf_font_semibold: str = "assets/fonts/Inter-SemiBold.ttf"
    pdf_font_light: str = "assets/fonts/Inter-Light.ttf"
    pdf_font_fallback: str = "assets/fonts/DejaVuSans.ttf"

    pdf_color_accent: str = "#1976d2"
    pdf_color_accent_light: str = "#e3f2fd"
    pdf_color_bg: str = "#fafafa"
    pdf_color_text: str = "#212121"
    pdf_color_text_secondary: str = "#888888"
    pdf_color_weekend: str = "#e8eaf6"
    pdf_color_empty: str = "#f5f5f5"
    pdf_color_today_border: str = "#1976d2"
    pdf_color_friday: str = "#fff3e0"
    pdf_color_grid: str = "#e0e0e0"

    pdf_cell_size_mm: int = 25
    pdf_margin_mm: int = 3
    pdf_gap_mm: int = 2
    pdf_corner_radius: int = 4

    pdf_open_after_generate: bool = False

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


class Settings(BaseSettings):
    # Telegram
    use_telegram: bool = False
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None

    # Database
    database_url: str = "sqlite:///prayers.db"

    # Monitoring
    monitor_alerts_enabled: bool = False

    # Дефолтный профиль (используется как fallback / для тестов)
    prayer_latitude: float = 55.7558
    prayer_longitude: float = 37.6173
    prayer_timezone: str = "Europe/Moscow"
    prayer_use_hanafi: bool = True
    prayer_fajr_angle: float = 16.0
    prayer_isha_angle: float = 15.0

    # PDF
    pdf: PDFSettings = PDFSettings()

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

USE_TELEGRAM = settings.use_telegram
BOT_TOKEN = settings.bot_token
CHAT_ID = settings.chat_id
DATABASE_URL = settings.database_url
MONITOR_ALERTS_ENABLED = settings.monitor_alerts_enabled
PDF_SETTINGS = settings.pdf

PRAYER_LATITUDE = settings.prayer_latitude
PRAYER_LONGITUDE = settings.prayer_longitude
PRAYER_TIMEZONE = settings.prayer_timezone
PRAYER_USE_HANAFI = settings.prayer_use_hanafi
PRAYER_FAJR_ANGLE = settings.prayer_fajr_angle
PRAYER_ISHA_ANGLE = settings.prayer_isha_angle
