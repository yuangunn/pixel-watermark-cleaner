"""Make the top-level ``clean`` module importable when running from source."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
