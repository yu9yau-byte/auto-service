"""Automatic SQLite database backups with rotation."""
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


def backup_database(db_path: Path, backup_dir: Path, keep_days: int = 30) -> Path | None:
    """
    Copy the database to backups/service_db_YYYYMMDD_HHMMSS.sqlite.
    Remove backups older than keep_days.
    """
    db_path = Path(db_path)
    if not db_path.is_file():
        logger.info("Backup skipped: database file not found (%s)", db_path)
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = backup_dir / f"service_db_{stamp}.sqlite"

    shutil.copy2(db_path, destination)
    logger.info("Database backup created: %s", destination)

    _rotate_backups(backup_dir, keep_days)
    return destination


def _rotate_backups(backup_dir: Path, keep_days: int) -> None:
    cutoff = datetime.now() - timedelta(days=keep_days)
    for path in sorted(backup_dir.glob("service_db_*.sqlite")):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                logger.info("Removed old backup: %s", path.name)
            except OSError as exc:
                logger.warning("Could not remove old backup %s: %s", path, exc)
