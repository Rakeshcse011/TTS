"""Optional PyInstaller entry point for the Streamlit desktop launcher."""

from __future__ import annotations

import sys
from pathlib import Path

from streamlit.web import cli

if getattr(sys, "frozen", False):
    app_path = Path(sys._MEIPASS) / "app.py"
else:
    app_path = Path(__file__).with_name("app.py")

sys.argv = ["streamlit", "run", str(app_path), "--global.developmentMode=false"]
raise SystemExit(cli.main())
