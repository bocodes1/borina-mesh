#!/usr/bin/env python
"""Detached Launch Studio runner (M5); the logic is in apps/api/dispatch/studio_runner.py.

Spawned with start_new_session so a mesh kickstart never kills a build halfway,
exactly like scripts/builder_run.py. One argument: --slug."""
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

from dispatch import studio_runner  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    a = ap.parse_args()
    print(f"[studio-run] {a.slug}: start", flush=True)
    kind = studio_runner.drive(a.slug)
    print(f"[studio-run] {a.slug}: {kind}", flush=True)


if __name__ == "__main__":
    main()
