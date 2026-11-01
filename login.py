"""
Одноразовый вход в Telegram для парсера чата.
Запуск: python login.py  -> введите api_id, api_hash, телефон и код из Telegram.
Скрипт выведет строку сессии — её нужно положить в секрет TG_SESSION репозитория.
Строка даёт доступ к аккаунту: никому её не пересылайте и не сохраняйте в файлах репозитория.
"""
from telethon.sync import TelegramClient
from telethon.sessions import StringSession

api_id = int(input("api_id: ").strip())
api_hash = input("api_hash: ").strip()
with TelegramClient(StringSession(), api_id, api_hash) as client:
    me = client.get_me()
    print("\nВход выполнен как", me.first_name, f"(@{me.username})" if me.username else "")
    print("\n=== Скопируйте строку ниже целиком в секрет TG_SESSION ===\n")
    print(client.session.save())
    print("\n=== конец строки ===")
