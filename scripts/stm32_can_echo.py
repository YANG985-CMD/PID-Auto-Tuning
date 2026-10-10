#!/usr/bin/env python3
"""Repository entry point for the CAN-only active diagnostic."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/motor-td3-serial-tuning/scripts"))
from can_echo_pil import main
if __name__ == "__main__": main()
