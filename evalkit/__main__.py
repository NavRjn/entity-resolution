import os
import sys

# Windows consoles default to cp1252; rich/tables print non-ASCII entity names.
os.environ.setdefault("PYTHONUTF8", "1")
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from evalkit.cli import main  # noqa: E402

main()
