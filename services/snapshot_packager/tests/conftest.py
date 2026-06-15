"""Test configuration for snapshot_packager.

Pre-registers services/snapshot_packager/main.py as the "main" module so
`import main` in test_build_api.py resolves to the correct file regardless of
test collection order (other services also have a main.py and with
--import-mode=importlib the first import wins in sys.modules).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_MAIN_PATH = Path(__file__).parent.parent / "main.py"
_spec = importlib.util.spec_from_file_location("main", _MAIN_PATH)
assert _spec and _spec.loader
_module = importlib.util.module_from_spec(_spec)
sys.modules["main"] = _module
_spec.loader.exec_module(_module)
