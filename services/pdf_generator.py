"""
Модуль генерации PDF-календаря намазов.
Формат A4 portrait (книжная ориентация).

Структура страницы:
  ┌─────────────────────────────────────────────┐
  │  Расписание намазов на Май 2026 г.          │  ← заголовок 18pt
  │  г. Грозный                                 │  ← подзаголовок 12pt
  ├──────┬────────┬───────┬──────┬──────┬───────┤
  │ Дата│ День   │ Фаджр │Восход│ Зухр │ Аср   │
  │     │ недели │       │      │      │       │
  ├──────┼────────┼───────┼──────┼──────┼───────┤
  │  1   │ Пт     │ 02:11 │04:41 │12:32 │16:33  │
  │  2   │ Сб     │ 02:10 │04:39 │12:32 │16:34  │
  │ ...  │        │       │      │      │       │
  │  31  │ Вс     │ 02:10 │04:39 │12:32 │16:34  │
  ├──────┴────────┴───────┴──────┴──────┴───────┤
  │  © part4_prayer_bot                         │
  └─────────────────────────────────────────────┘

Зависимости:
    - reportlab>=4.2.0
    - assets/fonts/DejaVuSans.ttf (для кириллицы)
"""

import asyncio
import logging
import os
import subprocess
import sys
from calendar import monthrange
from datetime import datetime, date
from typing import Optional, List, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from db.database import get_connection
from db.crud import get_by_month
from settings import PDF_SETTINGS

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Константы
# ──────────────────────────────────────────────

# A4 portrait: 595.28 x 841.89 pt
PAGE_W, PAGE_H = A4

MONTH_NAMES = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]

WEEKDAYS_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

PRAYER_COLUMNS = ["Фаджр", "Восход", "Зухр", "Аср", "Магриб", "Иша"]
PRAYER_DB_COLUMNS = ["fajr", "shurooq", "dhuhr", "asr", "maghrib", "isha"]

# Цветовая схема
HEADER_BG = colors.Color(0.106, 0.227, 0.361)   # #1B3A5C
HEADER_TEXT = colors.Color(1, 1, 1)               # #FFFFFF
ROW_ALT_BG = colors.Color(0.941, 0.957, 0.973)   # #F0F4F8
TEXT_BLACK = colors.Color(0, 0, 0)                # #000000
GRID_COLOR = colors.Color(0.816, 0.835, 0.867)    # #D0D5DD
FOOTER_COLOR = colors.Color(0.5, 0.5, 0.5)

# Выделение дней
FRIDAY_BG = colors.Color(0.85, 0.95, 0.85)        # светло-зелёный для пятницы
TODAY_BG = colors.Color(0.80, 0.90, 1.0)           # светло-синий для сегодня

# Поля страницы (в pt)
MARGIN = 40

# Доступные размеры
USABLE_W = PAGE_W - 2 * MARGIN  # 595.28 - 80 = 515.28 pt
USABLE_H = PAGE_H - 2 * MARGIN  # 841.89 - 80 = 761.89 pt


def _get_prayer_data(year: int, month: int) -> List[Tuple]:
    """Получает данные о времени намазов из БД для указанного месяца."""
    conn = get_connection()
    try:
        rows = get_by_month(conn, year, month)
        return rows
    except Exception as e:
        logger.error("❌ Ошибка получения данных из БД: %s", e)
        return []
    finally:
        conn.close()


def _is_today(year: int, month: int, day: int) -> bool:
    """Проверяет, является ли указанная дата сегодняшним днём."""
    today = date.today()
    return today.year == year and today.month == month and today.day == day


def _is_friday(year: int, month: int, day: int) -> bool:
    """Проверяет, является ли день пятницей."""
    try:
        return date(year, month, day).weekday() == 4
    except (ValueError, OverflowError):
        return False


def _register_fonts() -> str:
    """Регистрирует TTF-шрифты. Возвращает имя основного шрифта."""
    font_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "assets", "fonts",
    )

    # Пробуем DejaVuSans (поддерживает кириллицу)
    dejavu_path = os.path.join(font_dir, "DejaVuSans.ttf")
    if os.path.exists(dejavu_path):
        try:
            pdfmetrics.registerFont(TTFont("DejaVuSans", dejavu_path))
            logger.info("✅ DejaVuSans загружен как основной шрифт")
            return "DejaVuSans"
        except Exception as e:
            logger.warning("⚠️ Ошибка загрузки DejaVuSans: %s", e)

    logger.warning("⚠️ DejaVuSans не найден, используется Helvetica")
    return "Helvetica"


def generate_pdf(
    year: int,
    month: int,
    filepath: Optional[str] = None,
    city: str = "г. Грозный",
) -> Optional[str]:
    """
    Генерирует PDF-календарь намазов для указанного месяца.
    Формат A4 portrait (книжная ориентация).

    Таблица: Дата | День недели | Фаджр | Восход | Зухр | Аср | Магриб | Иша

    Args:
        year: Год (например, 2026)
        month: Месяц (1-12)
        filepath: Путь для сохранения файла.
        city: Название города для подзаголовка.

    Returns:
        Путь к сгенерированному PDF-файлу или None при ошибке.
    """
    logger.info("📄 Начало генерации PDF для %d-%02d", year, month)

    font_name = _register_fonts()

    # Получаем данные из БД
    prayer_data = _get_prayer_data(year, month)

    # Строим словарь: date_str -> {fajr, shurooq, dhuhr, asr, maghrib, isha}
    prayer_map = {}
    for row in prayer_data:
        prayer_map[row[0]] = {
            "fajr": row[1] or "",
            "shurooq": row[2] or "",
            "dhuhr": row[3] or "",
            "asr": row[4] or "",
            "maghrib": row[5] or "",
            "isha": row[6] or "",
        }

    # Формируем имя файла
    month_name = MONTH_NAMES[month]
    if filepath is None:
        output_dir = PDF_SETTINGS.pdf_output_dir
        if output_dir == ".":
            output_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        filepath = os.path.join(output_dir, f"Расписание_намазов_{month_name}_{year}.pdf")

    # Создаём документ
    try:
        doc = SimpleDocTemplate(
            filepath,
            pagesize=A4,
            leftMargin=MARGIN,
            rightMargin=MARGIN,
            topMargin=MARGIN,
            bottomMargin=MARGIN,
            title=f"Расписание намазов на {month_name} {year} года",
            author="Prayer Bot",
            subject=f"Время намазов на {month_name} {year}",
            keywords=f"намаз,расписание,{month_name},{year},ислам,молитва",
            creator="Prayer Bot",
        )

        elements = []

        # ── Заголовок (18pt) ──
        title_style = ParagraphStyle(
            "Title",
            fontName=font_name,
            fontSize=18,
            leading=22,
            textColor=TEXT_BLACK,
            alignment=TA_CENTER,
            spaceAfter=2,
        )
        elements.append(Paragraph(
            f"Расписание намазов на {month_name} {year} г.",
            title_style,
        ))

        # ── Подзаголовок (12pt) ──
        subtitle_style = ParagraphStyle(
            "Subtitle",
            fontName=font_name,
            fontSize=12,
            leading=15,
            textColor=TEXT_BLACK,
            alignment=TA_CENTER,
            spaceAfter=8,
        )
        elements.append(Paragraph(city, subtitle_style))

        # ── Построение таблицы ──
        _, days_in_month = monthrange(year, month)

        # Заголовки таблицы
        headers = ["Дата", "День", "Фаджр", "Восход", "Зухр", "Аср", "Магриб", "Иша"]

        # Стили
        header_style = ParagraphStyle(
            "Header",
            fontName=font_name,
            fontSize=10,
            leading=12,
            textColor=HEADER_TEXT,
            alignment=TA_CENTER,
        )
        cell_style = ParagraphStyle(
            "Cell",
            fontName=font_name,
            fontSize=9,
            leading=10.8,  # межстрочный 1.2
            textColor=TEXT_BLACK,
            alignment=TA_CENTER,
        )
        day_cell_style = ParagraphStyle(
            "DayCell",
            fontName=font_name,
            fontSize=9,
            leading=10.8,
            textColor=TEXT_BLACK,
            alignment=TA_CENTER,
        )
        weekday_cell_style = ParagraphStyle(
            "WeekdayCell",
            fontName=font_name,
            fontSize=9,
            leading=10.8,
            textColor=TEXT_BLACK,
            alignment=TA_CENTER,
        )

        # Формируем данные таблицы
        table_data = []

        # Строка заголовков
        header_row = [Paragraph(h, header_style) for h in headers]
        table_data.append(header_row)

        # Строки с данными
        for day_num in range(1, days_in_month + 1):
            date_str = f"{year}-{month:02d}-{day_num:02d}"
            wd = date(year, month, day_num).weekday()  # 0=Пн, 6=Вс
            weekday_short = WEEKDAYS_SHORT[wd]

            prayers = prayer_map.get(date_str, {})

            row = [
                Paragraph(str(day_num), day_cell_style),
                Paragraph(weekday_short, weekday_cell_style),
                Paragraph(prayers.get("fajr", ""), cell_style),
                Paragraph(prayers.get("shurooq", ""), cell_style),
                Paragraph(prayers.get("dhuhr", ""), cell_style),
                Paragraph(prayers.get("asr", ""), cell_style),
                Paragraph(prayers.get("maghrib", ""), cell_style),
                Paragraph(prayers.get("isha", ""), cell_style),
            ]
            table_data.append(row)

        # ── Расчёт ширины колонок ──
        # Дата: 28pt, День недели: 32pt, остальные 6 колонок поровну
        date_w = 48
        weekday_w = 48
        remaining = USABLE_W - date_w - weekday_w
        prayer_col_w = remaining / 6  # ~75.88 pt

        col_widths = [date_w, weekday_w] + [prayer_col_w] * 6

        # ── Расчёт высоты строк ──
        # Доступная высота: USABLE_H
        # Заголовок: ~24pt (18 + 2 + 4)
        # Подзаголовок: ~23pt (12 + 8 + 3)
        # Нижний колонтитул: ~15pt
        # Шапка таблицы: ~24pt (10pt шрифт + отступы)
        # Остальное на строки данных
        header_height = 24
        data_rows_count = days_in_month
        available_for_rows = USABLE_H - 24 - 23 - 15 - header_height
        row_height = available_for_rows / data_rows_count

        # Ограничиваем минимальную высоту строки
        if row_height < 16:
            row_height = 16
            logger.warning("⚠️ Строки могут не поместиться на одну страницу: %.1f pt", row_height)

        row_heights = [header_height] + [row_height] * data_rows_count

        table = Table(table_data, colWidths=col_widths, rowHeights=row_heights)

        # ── Стиль таблицы ──
        style_cmds = [
            # Выравнивание
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),

            # Шапка
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), HEADER_TEXT),

            # Сетка (все линии)
            ("GRID", (0, 0), (-1, -1), 0.5, GRID_COLOR),

            # Внутренние отступы в ячейках
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]

        # Чередование строк (zebra striping) — для строк данных (начиная с индекса 1)
        for row_idx in range(1, len(table_data)):
            if row_idx % 2 == 0:
                style_cmds.append(
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), ROW_ALT_BG)
                )

        # Выделение пятницы (зелёный фон для всей строки)
        for row_idx in range(1, len(table_data)):
            day_num = row_idx  # строки идут по порядку с 1
            if _is_friday(year, month, day_num):
                style_cmds.append(
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), FRIDAY_BG)
                )

        # Выделение сегодняшнего дня (синий фон)
        for row_idx in range(1, len(table_data)):
            day_num = row_idx
            if _is_today(year, month, day_num):
                style_cmds.append(
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), TODAY_BG)
                )

        # Визуальная группировка временных колонок:
        # Добавляем лёгкую вертикальную линию между "День недели" и "Фаджр"
        # и тонкую линию после последней колонки данных
        # Используем INNERGRID для выделения области данных
        style_cmds.append(
            ("LINEAFTER", (1, 0), (1, -1), 1.0, HEADER_BG)  # жирная линия после "День недели"
        )

        table.setStyle(TableStyle(style_cmds))
        elements.append(table)

        # ── Нижний колонтитул ──
        # elements.append(Spacer(1, 6))
        # footer_style = ParagraphStyle(
        #     "Footer",
        #     fontName=font_name,
        #     fontSize=8,
        #     leading=10,
        #     textColor=FOOTER_COLOR,
        #     alignment=TA_CENTER,
        # )
        # elements.append(Paragraph("© part4_prayer_bot", footer_style))

        # Собираем документ
        doc.build(elements)

        file_size = os.path.getsize(filepath)
        logger.info(
            "✅ PDF сгенерирован: %s (%d KB, %d дней)",
            filepath,
            file_size // 1024,
            days_in_month,
        )

        # Открыть PDF после генерации (если разрешено)
        if PDF_SETTINGS.pdf_open_after_generate:
            _open_pdf(filepath)

        return filepath

    except Exception as e:
        logger.error("❌ Ошибка генерации PDF: %s", e)
        import traceback
        logger.error(traceback.format_exc())
        return None


async def async_generate_pdf(
    year: int,
    month: int,
    filepath: Optional[str] = None,
    city: str = "г. Москва",
) -> Optional[str]:
    """
    Асинхронная версия generate_pdf().
    Запускает генерацию в отдельном потоке, чтобы не блокировать event loop.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, generate_pdf, year, month, filepath, city,
    )


def _open_pdf(filepath: str) -> None:
    """Открывает PDF-файл в системном просмотрщике."""
    try:
        if sys.platform == "win32":
            os.startfile(filepath)
        elif sys.platform == "darwin":
            subprocess.run(["open", filepath], check=False)
        else:  # Linux
            subprocess.run(["xdg-open", filepath], check=False)
        logger.info("📂 PDF открыт: %s", filepath)
    except Exception as e:
        logger.warning("⚠️ Не удалось открыть PDF: %s", e)
