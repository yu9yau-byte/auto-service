"""Application configuration (paths, backup, card reader)."""
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

DB_PATH = APP_DIR / "service_db.sqlite"

LOG_DIR = APP_DIR / "logs"
LOG_FILE = LOG_DIR / "app.log"

BACKUP_DIR = APP_DIR / "backups"
BACKUP_KEEP_DAYS = 30

CARD_WAIT_TIMEOUT_SEC = 30
CARD_POLL_INTERVAL_SEC = 1
