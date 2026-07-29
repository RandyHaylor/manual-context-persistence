"""Make the repository root importable so tests run without an install step."""
import os
import sys

REPOSITORY_ROOT_DIRECTORY = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPOSITORY_ROOT_DIRECTORY not in sys.path:
    sys.path.insert(0, REPOSITORY_ROOT_DIRECTORY)
