#!/usr/bin/env python3
"""Universal launcher for the Wolf Territory Map app."""

import subprocess
import sys
from pathlib import Path


def main():
    # Ensure we run from the Wolfapp directory
    app_dir = Path(__file__).resolve().parent
    app_script = app_dir / "app" / "wolf_map.py"

    if not app_script.exists():
        print(f"Error: Could not find {app_script}")
        sys.exit(1)

    # Check that streamlit is installed
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print("Error: Streamlit is not installed.")
        print("Install dependencies with:  pip install -r requirements.txt")
        sys.exit(1)

    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_script)],
        cwd=str(app_dir),
    )


if __name__ == "__main__":
    main()
