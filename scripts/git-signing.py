#!/usr/bin/env python3
from pathlib import Path
import runpy


runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "plugins/git-account/scripts/git_signing.py"),
    run_name="__main__",
)
