#!/usr/bin/env python3
"""Big-bang migration: read the existing Obsidian vault and propose
everything signal-worthy to the wiki engine via /memory/propose.

This script is meant to run ONCE. It:

1. Walks the vault (excluding the new wiki directories: entities/, concepts/,
   decisions/, sources/, _queue/, _archive/, 00-schema.md, index.md, log.md,
   curator-memory.md).
2. For each file, reads the content.
3. Chunks large files into ~4KB segments to stay under reviewer context limits.
4. Submits each chunk as a proposal to /memory/propose with source="migration".
5. After all proposals are queued, optionally triggers /wiki/review to process
   them in batches until the queue is empty.
6. Moves each successfully-processed file into _archive/ to avoid re-ingesting
   on re-runs.

Usage:
    python scripts/migrate_vault.py \\
        --vault /path/to/vault \\
        --api http://100.116.121.128:8000 \\
        [--dry-run] \\
        [--max-files N]

Run this on the Mac Mini (where the Borina API lives) or on the PC over
Tailscale.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Iterator


EXCLUDED_TOPLEVEL = {
    "entities", "concepts", "decisions", "sources",
    "_queue", "_archive",
    "00-schema.md", "index.md", "log.md", "curator-memory.md",
}

# Files we definitely don't want to curate (binary, config, build artifacts)
SKIP_PATTERNS = {
    ".git", ".obsidian", "node_modules", ".next", "__pycache__",
    ".DS_Store", ".venv", "venv", "dist", "build",
}

# Only these extensions get ingested
TEXT_EXTENSIONS = {".md", ".txt", ".org"}

CHUNK_SIZE = 4000  # chars — stays safely under reviewer context budget


def should_skip(path: Path, vault_root: Path) -> bool:
    """Return True if path should be excluded from migration."""
    try:
        rel = path.relative_to(vault_root)
    except ValueError:
        return True

    # Top-level exclusion (the new wiki directories)
    parts = rel.parts
    if parts and parts[0] in EXCLUDED_TOPLEVEL:
        return True

    # Pattern-based skipping (walks up the path)
    for part in parts:
        if part in SKIP_PATTERNS:
            return True

    # Extension filter
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return True

    return False


def iter_vault_files(vault_root: Path) -> Iterator[Path]:
    """Yield every file to migrate, in deterministic order."""
    for root, dirs, files in os.walk(vault_root):
        root_path = Path(root)
        # Prune excluded dirs to avoid walking them
        dirs[:] = [d for d in dirs if d not in SKIP_PATTERNS and d not in EXCLUDED_TOPLEVEL]
        for fname in sorted(files):
            path = root_path / fname
            if not should_skip(path, vault_root):
                yield path


def chunk_content(content: str, chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Split content into chunks, breaking on paragraph boundaries where possible."""
    if len(content) <= chunk_size:
        return [content]

    chunks: list[str] = []
    remaining = content
    while len(remaining) > chunk_size:
        # Try to break on a double-newline near the chunk boundary
        split_at = remaining.rfind("\n\n", 0, chunk_size)
        if split_at < chunk_size // 2:
            split_at = chunk_size
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks


def post_proposal(api_url: str, payload: dict, retries: int = 3) -> dict | None:
    """POST to /memory/propose with retries."""
    req = urllib.request.Request(
        f"{api_url}/memory/propose",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            if attempt == retries - 1:
                print(f"  ERROR: {e}", file=sys.stderr)
                return None
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"  unexpected error: {e}", file=sys.stderr)
            return None
    return None


def trigger_review(api_url: str, max_items: int = 50) -> dict | None:
    """Call POST /wiki/review to process the queued proposals."""
    req = urllib.request.Request(
        f"{api_url}/wiki/review?max_items={max_items}",
        data=b"",
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"review trigger failed: {e}", file=sys.stderr)
        return None


def archive_file(source: Path, vault_root: Path) -> None:
    """Move a processed file into _archive/, preserving relative structure."""
    rel = source.relative_to(vault_root)
    dest = vault_root / "_archive" / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Use rename; if cross-device, fall back to copy+delete
    try:
        source.rename(dest)
    except OSError:
        import shutil
        shutil.copy2(source, dest)
        source.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vault", required=True, help="Path to the Obsidian vault root")
    parser.add_argument("--api", required=True, help="Borina API base URL")
    parser.add_argument("--dry-run", action="store_true", help="Walk and print but don't post")
    parser.add_argument("--max-files", type=int, default=None, help="Limit the number of files processed")
    parser.add_argument("--archive", action="store_true", help="Move processed files into _archive/")
    parser.add_argument("--review-after", action="store_true", help="Trigger /wiki/review batches after queueing")
    args = parser.parse_args()

    vault_root = Path(args.vault).expanduser().resolve()
    if not vault_root.exists():
        print(f"ERROR: vault not found: {vault_root}", file=sys.stderr)
        return 1

    print(f"Vault: {vault_root}")
    print(f"API:   {args.api}")
    print(f"Dry run: {args.dry_run}")
    print()

    files_processed = 0
    chunks_posted = 0
    chunks_failed = 0

    for path in iter_vault_files(vault_root):
        if args.max_files and files_processed >= args.max_files:
            print(f"Reached --max-files limit ({args.max_files}), stopping")
            break

        rel = path.relative_to(vault_root)
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"skip (read error): {rel}: {e}")
            continue

        if not content.strip():
            continue

        chunks = chunk_content(content)
        print(f"[{files_processed+1}] {rel}  ({len(content)} chars, {len(chunks)} chunks)")

        file_had_success = False
        for i, chunk in enumerate(chunks):
            payload = {
                "source": "migration",
                "agent_id": "migration",
                "prompt": f"Existing vault content: {rel} (chunk {i+1}/{len(chunks)})",
                "content": chunk,
            }
            if args.dry_run:
                chunks_posted += 1
                file_had_success = True
                continue

            result = post_proposal(args.api, payload)
            if result and result.get("queued"):
                chunks_posted += 1
                file_had_success = True
            else:
                chunks_failed += 1

            # Small sleep to avoid overwhelming the API
            time.sleep(0.05)

        files_processed += 1

        if args.archive and file_had_success and not args.dry_run:
            try:
                archive_file(path, vault_root)
            except Exception as e:
                print(f"  archive failed for {rel}: {e}", file=sys.stderr)

    print()
    print(f"Files processed: {files_processed}")
    print(f"Chunks queued:   {chunks_posted}")
    print(f"Chunks failed:   {chunks_failed}")

    if args.review_after and not args.dry_run:
        print("\nTriggering review batches...")
        while True:
            summary = trigger_review(args.api, max_items=20)
            if summary is None:
                print("review trigger failed; stopping")
                break
            print(f"  processed={summary['processed']} approved={summary['approved']} rejected={summary['rejected']} errors={summary['errors']}")
            if summary["processed"] == 0:
                break
            time.sleep(1)

    return 0


if __name__ == "__main__":
    sys.exit(main())
