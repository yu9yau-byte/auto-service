"""Copy patched modules from AUTO SERVICE_CODEX into this project."""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CODEX = ROOT.parent / "AUTO SERVICE_CODEX"

FILES = [
    "database.py",
    "service_app.py",
    "repository.py",
    "entity_dialogs.py",
    "order_dialog.py",
    "order_edit_dialog.py",
    "requirements.txt",
]

for name in FILES:
    src = CODEX / name
    if src.is_file():
        shutil.copy2(src, ROOT / name)
        print("copied", name)

test_src = CODEX / "tests" / "test_core.py"
if test_src.is_file():
    (ROOT / "tests").mkdir(exist_ok=True)
    shutil.copy2(test_src, ROOT / "tests" / "test_core.py")
    print("copied tests/test_core.py")

print("done")
