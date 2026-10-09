#!/usr/bin/env python
"""Detached Launch Studio radar job (M5); the logic is in apps/api/dispatch/studio_radar.py.

Spawned with start_new_session, like scripts/studio_run.py, so a mesh kickstart
during the ~40 min run never loses the briefs it writes. One flag: --force
(Bo's /studio radar: ignores quiet hours, never the STUDIO_ENABLED switch)."""
import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
API = REPO / "apps" / "api"
sys.path.insert(0, str(API))
os.chdir(API)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(API / ".env")

from dispatch import studio_radar  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    print(f"[studio-radar] start (force={a.force})", flush=True)
    print(f"[studio-radar] {studio_radar.run_radar_job(force=a.force)}", flush=True)


if __name__ == "__main__":
    main()
