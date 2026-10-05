#!/usr/bin/env python3
"""Kept for old habits: runs the full pipeline. Use `python3 main.py` instead."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from main import run

if __name__ == "__main__":
    sys.exit(run())
