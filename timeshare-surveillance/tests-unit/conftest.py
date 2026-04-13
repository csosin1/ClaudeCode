"""Shared pytest setup for tests-unit/.

Pushes the project root onto sys.path so `from pipeline import ...` and
`from config import ...` work regardless of where pytest is invoked from.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
