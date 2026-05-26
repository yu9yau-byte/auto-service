"""
Sync app modules from AUTO SERVICE_CODEX (if needed) and apply tech-debt patches.
Run from project folder: python apply_tech_debt.py
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT.parent / "AUTO SERVICE_CODEX"

SKIP = {
    "read_card_v2.py",
    "config.py",
    "app_logging.py",
    "backup.py",
    "billing.py",
    "requirements.txt",
    "constants.py",
    "TECH_DEBT_CHANGES.md",
    "_sync_from_codex.py",
    "apply_tech_debt.py",
}


def sync_from_codex() -> None:
    if not SRC.is_dir():
        print(f"Source not found: {SRC}")
        return
    for path in SRC.iterdir():
        if path.is_file() and path.name not in SKIP:
            shutil.copy2(path, ROOT / path.name)
            print("copied", path.name)
    tests_src = SRC / "tests"
    if tests_src.is_dir():
        (ROOT / "tests").mkdir(exist_ok=True)
        for path in tests_src.glob("test_*.py"):
            if path.name not in ("test_billing.py", "test_backup.py"):
                shutil.copy2(path, ROOT / "tests" / path.name)
                print("copied tests/", path.name)


def patch_database(text: str) -> str:
    if "from billing import" not in text:
        text = text.replace(
            "import sqlite3\nfrom datetime import",
            "import logging\nimport sqlite3\nfrom datetime import",
        )
        text = text.replace(
            "from constants import OrderStatus, PartStatus, PaymentStatus, VAT_MULTIPLIER\nfrom repository import OrderRepository\n",
            "import config\nfrom billing import line_totals_with_vat, split_unit_price_with_vat\n"
            "from constants import OrderStatus, PartStatus, PaymentStatus\nfrom repository import OrderRepository\n\n"
            "logger = logging.getLogger(__name__)\n",
        )
    text = text.replace(
        "    def __init__(self, db_path='service_db.sqlite'):\n        self.db_path = db_path\n",
        "    def __init__(self, db_path=None):\n        self.db_path = str(db_path if db_path is not None else config.DB_PATH)\n",
    )
    text = text.replace(
        "        self.connection.execute('PRAGMA foreign_keys = ON')\n        return self.connection\n",
        "        self.connection.execute('PRAGMA foreign_keys = ON')\n"
        "        self.connection.execute('PRAGMA journal_mode = WAL')\n        return self.connection\n",
    )
    text = text.replace(
        '        print(f"Database ready: {self.db_path}")\n',
        '        logger.info("Database ready: %s", self.db_path)\n',
    )
    old_add = """        price_without_vat = round(price_with_vat / VAT_MULTIPLIER, 2)
        vat_amount = round(price_with_vat - price_without_vat, 2)
        subtotal_with_vat = round(price_with_vat * quantity, 2)
        subtotal_without_vat = round(price_without_vat * quantity, 2)

        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO order_services"""
    new_add = """        price_without_vat, vat_amount, _ = split_unit_price_with_vat(price_with_vat)
        subtotal_without_vat, vat_total, subtotal_with_vat = line_totals_with_vat(price_with_vat, quantity)

        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO order_services"""
    text = text.replace(old_add, new_add, 1)
    text = text.replace(
        """        price_without_vat = round(new_price / 1.20, 2)
        vat_amount = round(new_price - price_without_vat, 2)
        subtotal_with_vat = round(new_price * new_qty, 2)
        subtotal_without_vat = round(price_without_vat * new_qty, 2)""",
        """        price_without_vat, vat_amount, _ = split_unit_price_with_vat(new_price)
        subtotal_without_vat, vat_total, subtotal_with_vat = line_totals_with_vat(new_price, new_qty)""",
        1,
    )
    return text


def patch_repository(text: str) -> str:
    text = text.replace(
        "from constants import PartStatus, VAT_MULTIPLIER\n",
        "from billing import line_totals_with_vat, split_unit_price_with_vat\n"
        "from constants import PartStatus\n",
    )
    text = text.replace(
        """                price_without_vat = round(price_with_vat / VAT_MULTIPLIER, 2)
                vat_amount = round(price_with_vat - price_without_vat, 2)
                subtotal_with_vat = round(price_with_vat * quantity, 2)
                subtotal_without_vat = round(price_without_vat * quantity, 2)""",
        """                price_without_vat, vat_amount, _ = split_unit_price_with_vat(price_with_vat)
                subtotal_without_vat, vat_total, subtotal_with_vat = line_totals_with_vat(
                    price_with_vat, quantity
                )""",
        1,
    )
    return text


def patch_service_app(text: str) -> str:
    if "from app_logging import setup_logging" not in text:
        text = text.replace(
            "import sys\nimport threading\n",
            "import logging\nimport sys\nimport threading\n",
        )
        text = text.replace(
            "from read_card_v2 import get_card_data\n",
            "import config\nfrom app_logging import setup_logging\nfrom backup import backup_database\n"
            "from read_card_v2 import get_card_data\n",
        )
    text = text.replace(
        "class CardReaderSignals(QObject):\n    data_ready = pyqtSignal(dict)\n    error = pyqtSignal(str)\n    finished = pyqtSignal()\n",
        "class CardReaderSignals(QObject):\n    data_ready = pyqtSignal(dict)\n    error = pyqtSignal(str)\n    status = pyqtSignal(str)\n    finished = pyqtSignal()\n",
    )
    text = text.replace(
        "        self.db = ServiceDatabase()\n",
        "        self.db = ServiceDatabase(str(config.DB_PATH))\n",
    )
    if "self.card_signals.status.connect" not in text:
        text = text.replace(
            "        self.card_signals.finished.connect(self.on_card_reader_finished)\n\n        self.init_ui()\n",
            "        self.card_signals.finished.connect(self.on_card_reader_finished)\n"
            "        self.card_signals.status.connect(self.on_card_reader_status)\n\n"
            "        backup_path = backup_database(\n"
            "            config.DB_PATH, config.BACKUP_DIR, config.BACKUP_KEEP_DAYS\n"
            "        )\n"
            "        if backup_path:\n"
            "            logging.getLogger(__name__).info('Startup backup: %s', backup_path)\n\n"
            "        self.init_ui()\n",
        )
    text = text.replace(
        '        self.statusBar().showMessage("⏳ Ожидание карты в считывателе...")\n',
        '        self.statusBar().showMessage("⏳ Вставьте карту в считыватель (до 30 сек)...")\n',
    )
    text = text.replace(
        "    def _read_card_worker(self):\n        result = get_card_data()\n",
        "    def _read_card_worker(self):\n"
        "        def on_status(message):\n"
        "            self.card_signals.status.emit(message)\n\n"
        "        result = get_card_data(status_callback=on_status)\n",
    )
    if "def on_card_reader_status" not in text:
        text = text.replace(
            "    def on_card_reader_finished(self):\n",
            "    def on_card_reader_status(self, message):\n"
            "        self.statusBar().showMessage(message)\n\n"
            "    def on_card_reader_finished(self):\n",
        )
    text = text.replace(
        "        except:\n            year = None\n",
        "        except (ValueError, TypeError):\n            year = None\n",
    )
    text = text.replace(
        "def main():\n    app = QApplication(sys.argv)\n",
        "def main():\n    setup_logging(config.LOG_DIR, config.LOG_FILE)\n    app = QApplication(sys.argv)\n",
    )
    return text


def patch_file(name: str, patcher) -> None:
    path = ROOT / name
    if not path.is_file():
        print("skip (missing):", name)
        return
    original = path.read_text(encoding="utf-8")
    updated = patcher(original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        print("patched", name)
    else:
        print("unchanged", name)


def main() -> None:
    sync_from_codex()
    patch_file("database.py", patch_database)
    patch_file("repository.py", patch_repository)
    patch_file("service_app.py", patch_service_app)
    print("Done. Run: python -m unittest discover -s tests -v")


if __name__ == "__main__":
    main()
