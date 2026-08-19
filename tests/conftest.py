from __future__ import annotations

import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
os.environ.setdefault(
    "PIPHI_AUTOMATION_LEDGER_PATH",
    f"/tmp/piphi-433mhz-automation-actions-{os.getpid()}.sqlite3",
)
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))
