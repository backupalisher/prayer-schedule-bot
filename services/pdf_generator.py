from calendar import month_name

from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from db.database import get_connection
from datetime import datetime
from db.crud import get_by_month

def generate_pdf():

    conn = get_connection()
    pdfmetrics.registerFont(TTFont("DejaVu", "assets/fonts/DejaVuSans.ttf"))

    now = datetime.now()
    rows = get_by_month(conn, now.year, now.month)
    # Названия месяцев в именительном падеже
    month_names_nominative = [
        '', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
        'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь'
    ]
    month_name = month_names_nominative[now.month]

    if not rows:
        return None

    file_name = f"Расписание на {month_name}.pdf"
    doc = SimpleDocTemplate(file_name, pagesize=A4)

    styles = getSampleStyleSheet()

    elements = []

    # Заголовок
    title = Paragraph(
        "🕌 Расписание намазов",
        styles["Title"]
    )
    elements.append(title)

    elements.append(Spacer(1, 10))

    # Таблица
    data = [["Дата", "День", "Фаджр", "Шурук", "Зухр️", "Аср️", "Магриб", "Иша"]]

    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    for row in rows:
        date_obj = datetime.strptime(row[0], "%Y-%m-%d")
        weekday = weekdays[date_obj.weekday()]

        data.append([
            date_obj.strftime("%d.%m"),
            weekday,
            row[1],  # fajr
            row[2],  # shurooq
            row[3],  # dhuhr
            row[4],  # asr
            row[5],  # maghrib
            row[6],  # isha
        ])

    table = Table(data, colWidths=[25*mm]*8)

    style = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVu"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),

        ("BACKGROUND", (0, 0), (-1, 0), colors.darkgreen),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),

        ("ALIGN", (0, 0), (-1, -1), "CENTER"),

        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
    ])

    # 🔥 Выделение пятницы
    for i in range(1, len(data)):
        if data[i][1] == "Пт":
            style.add("BACKGROUND", (0, i), (-1, i), colors.lightgreen)
        if data[i][1] == "Сб":
            style.add("BACKGROUND", (0, i), (-1, i), colors.lightgrey)
        if data[i][1] == "Вс":
            style.add("BACKGROUND", (0, i), (-1, i), colors.lightgrey)

    table.setStyle(style)

    elements.append(table)

    doc.build(elements)

    conn.close()

    return file_name