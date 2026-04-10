# Инструкция по добавлению проекта в GitHub

Проект "Prayer" (Расписание намазов) готов к загрузке на GitHub. Все файлы добавлены в Git и создан коммит.

## Шаги для добавления на GitHub:

### 1. Создайте новый репозиторий на GitHub
1. Перейдите на [GitHub.com](https://github.com)
2. Нажмите кнопку "+" в правом верхнем углу и выберите "New repository"
3. Заполните информацию:
   - **Repository name**: prayer-schedule-bot (или другое название)
   - **Description**: Telegram бот для расписания намазов с парсингом с umma.ru
   - Выберите "Public" или "Private"
   - **Не добавляйте** README, .gitignore или license (они уже есть в проекте)

### 2. Добавьте удаленный репозиторий и отправьте код

Выполните следующие команды в терминале в папке проекта:

```bash
# Добавьте удаленный репозиторий (замените YOUR_USERNAME на ваш GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/prayer-schedule-bot.git

# Отправьте код на GitHub
git branch -M main
git push -u origin main
```

### 3. Альтернативный вариант через GitHub CLI

Если у вас установлен GitHub CLI:

```bash
# Создайте репозиторий
gh repo create prayer-schedule-bot --public --source=. --remote=origin --push
```

## Структура проекта

```
prayer-schedule-bot/
├── bot/              # Telegram бот
├── db/               # База данных и модели
├── parser/           # Парсер расписания с umma.ru
├── scheduler/        # Планировщик уведомлений
├── services/         # Сервисы (уведомления, PDF генерация)
├── assets/           # Ресурсы (шрифты)
├── main.py           # Главный файл приложения
├── config.py         # Конфигурация
├── requirements.txt  # Зависимости Python
├── README.md         # Описание проекта
└── .gitignore        # Исключаемые файлы
```

## Что было исправлено в проекте

1. **Исправлен вывод времени намаза** - были неправильные индексы столбцов в `services/prayer_service.py`
2. **Добавлено время Шурук** в вывод
3. **Создана новая база данных** с корректными временами
4. **Добавлен .gitignore** для исключения ненужных файлов

## Зависимости

Установите зависимости из `requirements.txt`:

```bash
pip install -r requirements.txt
```

Или используйте виртуальное окружение (уже есть `.venv/` в проекте).

## Запуск проекта

```bash
python main.py
```

Проект готов к использованию и дальнейшему развитию!