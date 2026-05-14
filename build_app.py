from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build SQL Splitter as a desktop app.")
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="create a single executable file instead of an app folder",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller is not installed. Run: python -m pip install -r requirements-build.txt")
        return 1

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "SQL-Splitter",
    ]
    if args.onefile:
        command.append("--onefile")
    command.append(str(root / "sql_split_gui.py"))

    return subprocess.call(command, cwd=root)


if __name__ == "__main__":
    raise SystemExit(main())
