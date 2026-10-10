#!/usr/bin/env python3
"""Repository entry point for the installable skill's CAN RAM diagnostic."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/motor-td3-serial-tuning/scripts"))
from can_loopback_pil import FIELDS, MODE, analyze, build, main, pil, run, validate_image

if __name__ == "__main__":
    main()
