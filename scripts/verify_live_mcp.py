#!/usr/bin/env python3
"""Run the live_mcp verification harness explicitly."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kairos.verification.live_mcp import main
if __name__ == "__main__":
    main()
