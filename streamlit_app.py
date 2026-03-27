# ReviZoR FranK — Streamlit Cloud entry point
# Streamlit Cloud looks for this file by default.
# It simply delegates to the main app module.
import runpy, sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
runpy.run_module("revizor_frank.app", run_name="__main__", alter_sys=True)
