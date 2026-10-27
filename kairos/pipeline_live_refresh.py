#!/usr/bin/env python3
"""Backward-compatibility alias wrapper for dataphase1_logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kairos.dataphase1_logic import *
from kairos.dataphase1_logic import main

if __name__ == "__main__":
    main()
