#!/usr/bin/env python
"""Deprecated — use scripts/sync_market_news.py."""

import subprocess
import sys
from pathlib import Path

raise SystemExit(
    subprocess.call([sys.executable, str(Path(__file__).with_name("sync_market_news.py"))])
)
