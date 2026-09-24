# config.py
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
CALENDAR_ID = "primary"

HORARIO_ATENCION = {
    0: (15, 18),  # Lunes 3pm-6pm
    1: (15, 18),  # Martes 3pm-6pm
    4: (15, 18),  # Viernes 3pm-6pm
    6: (15, 18),  # Domingo 3pm-6pm
}