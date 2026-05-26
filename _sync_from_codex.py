"""One-time sync of app modules from AUTO SERVICE_CODEX. Run: python _sync_from_codex.py"""
import shutil
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "AUTO SERVICE_CODEX"
DST = Path(__file__).resolve().parent

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
}

for path in SRC.iterdir():
    if path.name in SKIP:
        continue
    if path.is_file():
        shutil.copy2(path, DST / path.name)
        print("copied", path.name)

tests_src = SRC / "tests"
if tests_src.is_dir():
    (DST / "tests").mkdir(exist_ok=True)
    for path in tests_src.glob("*.py"):
        if path.name.startswith("test_"):
            shutil.copy2(path, DST / "tests" / path.name)
            print("copied tests/", path.name)

print("done")
