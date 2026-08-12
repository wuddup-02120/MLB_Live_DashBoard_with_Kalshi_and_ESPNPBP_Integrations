import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

KALSHI_API_KEY = os.getenv("KALSHI_API_KEY")

KALSHI_PRIVATE_KEY_PATH = (
    BASE_DIR / os.getenv("KALSHI_PRIVATE_KEY_PATH")
)