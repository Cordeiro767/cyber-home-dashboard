"""Application configuration from environment."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

SCAN_INTERVAL_SECONDS = max(10, int(os.getenv("SCAN_INTERVAL_SECONDS", "60")))
