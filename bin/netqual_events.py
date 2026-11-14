#!/usr/bin/env python3
"""Emit one JSON event per cycle with per-interface link quality."""
import sys

from netqual_common import discover, emit


def main():
    emit(discover())
    return 0


if __name__ == "__main__":
    sys.exit(main())
