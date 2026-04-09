#!/usr/bin/env python3
"""Wiki v2 nuclear reset.

Moves all v1 content (entities/, concepts/, decisions/, sources/) into
_archive/v1-nuked-2026-04-09/, purges the pending queue, creates the
new 5-category directory layout, and leaves index/log/curator-memory
for Task 3 to bootstrap.

Usage:
    python scripts/wiki_v2_reset.py --vault /path/to/vault
    python scripts/wiki_v2_reset.py --vault /path/to/vault --dry-run
"""

import argparse
import shutil
import sys
from datetime import date
from pathlib import Path


V1_DIRS = ["entities", "concepts", "decisions", "sources"]
V2_DIRS = ["trading", "ecommerce", "business", "infrastructure", "lessons"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    vault = Path(args.vault).expanduser().resolve()
    if not vault.exists():
        print(f"ERROR: vault not found: {vault}")
        return 1

    archive_dir = vault / "_archive" / f"v1-nuked-{date.today().isoformat()}"
    print(f"Vault: {vault}")
    print(f"Archive target: {archive_dir}")
    print(f"Dry run: {args.dry_run}")
    print()

    # 1. Move v1 dirs into archive
    for name in V1_DIRS:
        src = vault / name
        if not src.exists():
            print(f"  skip (missing): {name}/")
            continue
        dest = archive_dir / name
        file_count = sum(1 for _ in src.rglob("*") if _.is_file())
        print(f"  archive: {name}/ ({file_count} files) -> {dest}")
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dest))

    # 2. Purge pending queue
    pending = vault / "_queue" / "pending"
    if pending.exists():
        count = sum(1 for _ in pending.glob("*.json"))
        print(f"  purge: _queue/pending/ ({count} items)")
        if not args.dry_run:
            for f in pending.glob("*.json"):
                f.unlink()

    # 3. Create v2 category directories
    for name in V2_DIRS:
        d = vault / name
        print(f"  mkdir: {name}/")
        if not args.dry_run:
            d.mkdir(parents=True, exist_ok=True)

    # 4. Ensure _queue still exists for rejected.jsonl
    if not args.dry_run:
        (vault / "_queue" / "pending").mkdir(parents=True, exist_ok=True)

    print("\nDone." if not args.dry_run else "\nDry run complete — no changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
