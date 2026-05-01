#!/usr/bin/env python3
"""
Скрипт для добавления нового пользователя (chat_id) в базу данных.
"""

import sys
import os

# Добавляем путь к проекту для импорта модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from db.database import get_connection
from db.crud import insert_or_update_user, get_user_by_chat_id


def add_user(chat_id, username=None, first_name=None, last_name=None):
    """
    Добавляет пользователя в БД.
    
    Args:
        chat_id: ID чата пользователя (строка или число)
        username: Имя пользователя в Telegram (опционально)
        first_name: Имя пользователя (опционально)
        last_name: Фамилия пользователя (опционально)
    
    Returns:
        bool: True если успешно, False если ошибка
    """
    try:
        conn = get_connection()
        
        # Преобразуем chat_id в строку для единообразия
        chat_id_str = str(chat_id)
        
        # Проверяем, существует ли уже пользователь
        existing_user = get_user_by_chat_id(conn, chat_id_str)
        
        if existing_user:
            print(f"⚠️ Пользователь с chat_id={chat_id_str} уже существует в БД:")
            print(f"   ID: {existing_user[0]}")
            print(f"   Username: {existing_user[2]}")
            print(f"   Имя: {existing_user[3]}")
            print(f"   Фамилия: {existing_user[4]}")
            print(f"   Подписка: {'активна' if existing_user[5] else 'неактивна'}")
            print(f"   Создан: {existing_user[6]}")
            
            # Спросим, обновить ли данные
            response = input("Обновить данные пользователя? (y/N): ").strip().lower()
            if response != 'y':
                print("❌ Операция отменена.")
                conn.close()
                return False
        
        # Добавляем/обновляем пользователя
        success = insert_or_update_user(conn, chat_id_str, username, first_name, last_name)
        conn.close()
        
        if success:
            print(f"✅ Пользователь с chat_id={chat_id_str} успешно добавлен/обновлен в БД")
            return True
        else:
            print(f"❌ Не удалось добавить пользователя с chat_id={chat_id_str}")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка при работе с БД: {e}")
        return False


def list_users():
    """Выводит список всех пользователей из БД"""
    try:
        conn = get_connection()
        from db.crud import get_all_users
        users = get_all_users(conn)
        conn.close()
        
        if not users:
            print("📭 В БД нет пользователей")
            return
        
        print(f"📋 Найдено {len(users)} пользователей:")
        print("-" * 80)
        for user in users:
            print(f"ID: {user[0]}")
            print(f"  chat_id: {user[1]}")
            print(f"  username: {user[2] or 'не указан'}")
            print(f"  имя: {user[3] or 'не указано'}")
            print(f"  фамилия: {user[4] or 'не указана'}")
            print(f"  подписка: {'✅ активна' if user[5] else '❌ неактивна'}")
            print(f"  создан: {user[6]}")
            print(f"  обновлен: {user[7]}")
            print("-" * 80)
            
    except Exception as e:
        print(f"❌ Ошибка при получении списка пользователей: {e}")


def main():
    """Основная функция скрипта"""
    print("🕌 Скрипт управления пользователями БД расписания намазов")
    print("=" * 60)
    
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python add_user.py <chat_id> [username] [first_name] [last_name]")
        print("  python add_user.py --list  # показать всех пользователей")
        print("  python add_user.py --help  # показать эту справку")
        print()
        print("Примеры:")
        print("  python add_user.py 123456789")
        print("  python add_user.py 123456789 username Иван Иванов")
        print("  python add_user.py --list")
        return
    
    if sys.argv[1] == "--help" or sys.argv[1] == "-h":
        print("Добавление пользователя в БД для бота расписания намазов.")
        print()
        print("Аргументы:")
        print("  <chat_id>     - ID чата пользователя в Telegram (обязательно)")
        print("  [username]    - имя пользователя в Telegram (опционально)")
        print("  [first_name]  - имя пользователя (опционально)")
        print("  [last_name]   - фамилия пользователя (опционально)")
        print()
        print("Опции:")
        print("  --list, -l    - показать всех пользователей в БД")
        print("  --help, -h    - показать эту справку")
        return
    
    if sys.argv[1] == "--list" or sys.argv[1] == "-l":
        list_users()
        return
    
    # Добавление пользователя
    chat_id = sys.argv[1]
    
    # Получаем дополнительные аргументы
    username = sys.argv[2] if len(sys.argv) > 2 else None
    first_name = sys.argv[3] if len(sys.argv) > 3 else None
    last_name = sys.argv[4] if len(sys.argv) > 4 else None
    
    print(f"Добавление пользователя:")
    print(f"  chat_id: {chat_id}")
    print(f"  username: {username or 'не указан'}")
    print(f"  имя: {first_name or 'не указано'}")
    print(f"  фамилия: {last_name or 'не указана'}")
    print()
    
    add_user(chat_id, username, first_name, last_name)


if __name__ == "__main__":
    main()