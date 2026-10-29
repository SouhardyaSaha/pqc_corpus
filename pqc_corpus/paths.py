"""Project paths, independent of the working directory."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIRECTORY = PROJECT_ROOT / 'config'
COLLECTOR_DIRECTORY = PROJECT_ROOT / 'collector'
