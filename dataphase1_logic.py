#!/usr/bin/env python3
"""Convenience runner for KAIROS Phase 1 Data Logic."""

import os
import sys
from pathlib import Path

# Ensure workspace root is in python path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kairos.dataphase1_logic import main

if __name__ == "__main__":
    main()
