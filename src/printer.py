from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def print_pdf(pdf_path: str | Path) -> None:
    """Send a PDF to the OS default printer (skeleton)."""
    path = Path(pdf_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    if sys.platform.startswith("linux") or sys.platform == "darwin":
        subprocess.run(["lp", str(path)], check=True)
        return

    if sys.platform == "win32":
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Start-Process",
                "-FilePath",
                str(path),
                "-Verb",
                "Print",
            ],
            check=True,
        )
        return

    raise NotImplementedError(f"Unsupported OS: {sys.platform}")
