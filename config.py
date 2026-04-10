import os
from dotenv import load_dotenv

load_dotenv()

USE_TELEGRAM = os.getenv("USE_TELEGRAM", "False") == "True"
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
DATABASE_URL = "sqlite:///prayers.db"
MONITOR_ALERTS_ENABLED = os.getenv("MONITOR_ALERTS_ENABLED", "False") == "True"