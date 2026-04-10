import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
from db.database import get_connection
from db.crud import insert_prayer


def get_current_month_from_url(url):
    """Извлекает название месяца из URL или заголовка страницы"""
    try:
        # Пробуем взять месяц из URL (пример: /raspisanie-namaza/moscow/april-2026)
        if '/raspisanie-namaza/moscow/' in url:
            month_part = url.split('/raspisanie-namaza/moscow/')[-1]
            if month_part:
                return month_part.replace('-', ' ').title()
    except:
        pass
    return None


def parse_and_save():
    """Парсит расписание намазов с сайта umma.ru"""
    url = "https://umma.ru/raspisanie-namaza/moscow"

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # Добавляем retry логику для сетевых запросов
        for attempt in range(3):
            try:
                response = requests.get(url, headers=headers, timeout=15)
                response.raise_for_status()
                break
            except (requests.ConnectionError, requests.Timeout) as e:
                if attempt == 2:
                    print(f"❌ Ошибка сети после 3 попыток: {e}")
                    return False
                print(f"⚠️ Попытка {attempt + 1} не удалась, повтор через 2 секунды...")
                import time
                time.sleep(2)
        else:
            print("❌ Не удалось выполнить запрос после нескольких попыток")
            return False

        soup = BeautifulSoup(response.text, "html.parser")

        # 1. Определяем месяц и год
        # Пробуем найти заголовок h1
        title_tag = soup.find('h1')
        month_year_str = title_tag.get_text(strip=True) if title_tag else ""
        # Пример: "Время намаза на Апрель 2026 для Москва"

        # Извлекаем месяц и год из заголовка
        month_match = re.search(r'на (\w+) (\d{4})', month_year_str)
        if not month_match:
            # Альтернативный вариант: из URL
            month_from_url = get_current_month_from_url(url)
            if month_from_url:
                current_year = datetime.now().year
                month_year_str = f"{month_from_url} {current_year}"
                month_match = re.search(r'(\w+) (\d{4})', month_year_str)

        if not month_match:
            print("❌ Не удалось определить месяц и год, используем текущие")
            current_year = datetime.now().year
            current_month = datetime.now().month
        else:
            month_name = month_match.group(1)
            year = int(month_match.group(2))

            # Преобразуем название месяца на русском в номер
            months_ru = {
                'январь': 1, 'февраль': 2, 'март': 3, 'апрель': 4,
                'май': 5, 'июнь': 6, 'июль': 7, 'август': 8,
                'сентябрь': 9, 'октябрь': 10, 'ноябрь': 11, 'декабрь': 12
            }
            current_month = months_ru.get(month_name.lower(), datetime.now().month)
            current_year = year

        print(f"📅 Парсинг расписания на месяц {current_month}/{current_year}")

        # 2. Ищем таблицу
        table = soup.find('table', class_=re.compile(r'prayer-table|table'))
        if not table:
            table = soup.find('table')

        if not table:
            print("❌ Не удалось найти таблицу на странице")
            return False

        rows = table.find_all('tr')
        if len(rows) < 2:
            print("❌ Таблица пуста")
            return False

        # 3. Определяем индексы нужных столбцов
        header_row = rows[0]
        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(['th', 'td'])]

        # Ищем индексы (с учетом возможных вариаций)
        col_index = {
            'day': 0,  # Число/День
            'fajr': None,
            'shurooq': None,
            'dhuhr': None,
            'asr': None,
            'maghrib': None,
            'isha': None
        }

        for i, h in enumerate(headers):
            if 'фаджр' in h:
                col_index['fajr'] = i
            elif 'шурук' in h:
                col_index['shurooq'] = i
            elif 'зухр' in h:
                col_index['dhuhr'] = i
            elif 'аср' in h:
                col_index['asr'] = i
            elif 'магриб' in h:
                col_index['maghrib'] = i
            elif 'иша' in h:
                col_index['isha'] = i

        # Проверяем, что все нужные столбцы найдены
        required_cols = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']
        missing_cols = []
        for col in required_cols:
            if col_index[col] is None:
                missing_cols.append(col)

        if missing_cols:
            print(f"⚠️ Не найдены столбцы: {missing_cols}")
            print(f"Найденные заголовки: {headers}")
            # Пробуем использовать стандартные индексы как fallback
            # На сайте umma.ru обычно: 0-число, 1-фаджр, 2-шурук, 3-зухр, 4-аср, 5-магриб, 6-иша
            if len(headers) >= 7:
                print("📌 Используем стандартные индексы столбцов")
                col_index['fajr'] = 1
                col_index['shurooq'] = 2
                col_index['dhuhr'] = 3
                col_index['asr'] = 4
                col_index['maghrib'] = 5
                col_index['isha'] = 6
            else:
                return False

        print(f"✅ Индексы столбцов: день={col_index['day']}, фаджр={col_index['fajr']}, "
              f"шурук={col_index['shurooq']}, зухр={col_index['dhuhr']}, аср={col_index['asr']}, "
              f"магриб={col_index['maghrib']}, иша={col_index['isha']}")

        # 4. Парсим строки
        data = []

        for row in rows[1:]:  # Пропускаем заголовок
            cols = row.find_all('td')
            if len(cols) <= max(col_index.values()):
                continue

            # Извлекаем день месяца
            day_text = cols[col_index['day']].get_text(strip=True)
            # Извлекаем число из "1 Ср" или "2 Чт" или просто "1"
            day_match = re.search(r'^(\d+)', day_text)
            if not day_match:
                continue

            day = int(day_match.group(1))

            # Формируем дату с улучшенной обработкой ошибок
            try:
                date_obj = datetime(current_year, current_month, day)
                date_str = date_obj.strftime("%Y-%m-%d")
            except ValueError as e:
                print(f"⚠️ Ошибка создания даты для дня {day}: {e}")
                # Пропускаем невалидные даты (например, 31 февраля)
                continue

            # Получаем времена намазов
            fajr = cols[col_index['fajr']].get_text(strip=True)
            shurooq = cols[col_index['shurooq']].get_text(strip=True) if col_index['shurooq'] is not None else ""
            dhuhr = cols[col_index['dhuhr']].get_text(strip=True)
            asr = cols[col_index['asr']].get_text(strip=True)
            maghrib = cols[col_index['maghrib']].get_text(strip=True)
            isha = cols[col_index['isha']].get_text(strip=True)

            # Очистка времени от лишних символов
            def clean_time(time_str):
                # Оставляем только цифры и двоеточие
                cleaned = re.sub(r'[^\d:]', '', time_str)
                # Убираем лишние двоеточия
                parts = cleaned.split(':')
                if len(parts) >= 2:
                    # Нормализуем формат: добавляем ведущий ноль если нужно
                    hour = parts[0].zfill(2)
                    minute = parts[1].zfill(2) if len(parts[1]) > 0 else "00"
                    return f"{hour}:{minute}"
                return cleaned

            fajr = clean_time(fajr)
            shurooq = clean_time(shurooq)
            dhuhr = clean_time(dhuhr)
            asr = clean_time(asr)
            maghrib = clean_time(maghrib)
            isha = clean_time(isha)

            # Валидация времени (должно быть в формате ЧЧ:ММ)
            time_pattern = re.compile(r'^\d{1,2}:\d{2}$')
            times_to_check = [fajr, dhuhr, asr, maghrib, isha]
            if shurooq:
                times_to_check.append(shurooq)
            if not all(time_pattern.match(t) for t in times_to_check):
                print(f"⚠️ Неверный формат времени для {date_str}: "
                      f"Ф={fajr}, Ш={shurooq}, З={dhuhr}, А={asr}, М={maghrib}, И={isha}")
                continue

            data.append((date_str, fajr, shurooq, dhuhr, asr, maghrib, isha))

        if not data:
            print("❌ Не удалось извлечь данные из таблицы")
            return False

        # 5. Сохраняем в БД
        conn = get_connection()
        try:
            saved_count = 0
            for row in data:
                if insert_prayer(conn, row):
                    saved_count += 1

            print(f"✅ Парсер записал {saved_count} из {len(data)} дней в БД")

            # Возвращаем True, если хотя бы одна запись сохранена
            return saved_count > 0
        finally:
            conn.close()

    except requests.RequestException as e:
        print(f"❌ Ошибка сети: {e}")
        return False
    except Exception as e:
        print(f"❌ Непредвиденная ошибка: {e}")
        return False