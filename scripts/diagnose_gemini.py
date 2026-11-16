#!/usr/bin/env python3
"""Compatibility launcher for kairos.diagnostics.diagnose_gemini."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kairos.diagnostics.diagnose_gemini import main

if __name__ == "__main__":
    main()
