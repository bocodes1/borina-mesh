"""Run all 3 agents in parallel and collect results."""

import asyncio
import sys
import time
from datetime import date
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()


async def run_agent(name: str, module_name: str) -> tuple[str, bool, float]:
    """Run a single agent and return (name, success, duration_seconds)."""
    start = time.time()
    try:
        module = __import__(module_name)
        await module.run()
        duration = time.time() - start
        print(f"\n✓ {name} completed in {duration:.1f}s")
        return (name, True, duration)
    except Exception as e:
        duration = time.time() - start
        print(f"\n✗ {name} failed after {duration:.1f}s: {e}")
        return (name, False, duration)


async def main():
    """Dispatch all agents in parallel."""
    print(f"=== Daily Intelligence Pipeline — {date.today().isoformat()} ===\n")
    start = time.time()

    agents = [
        ("Ecommerce Scout", "ecommerce_scout"),
        ("Polymarket Intel", "polymarket_intel"),
        ("Adset Optimizer", "adset_optimizer"),
    ]

    # Run all agents concurrently
    results = await asyncio.gather(
        *[run_agent(name, module) for name, module in agents],
        return_exceptions=True,
    )

    # Summary
    total_time = time.time() - start
    print(f"\n{'='*50}")
    print(f"Pipeline complete in {total_time:.1f}s\n")

    for result in results:
        if isinstance(result, Exception):
            print(f"  ✗ Agent crashed: {result}")
        else:
            name, success, duration = result
            status = "✓" if success else "✗"
            print(f"  {status} {name}: {'OK' if success else 'FAILED'} ({duration:.1f}s)")

    # Check reports
    from shared.report import get_report_dir
    report_dir = get_report_dir()
    reports = list(report_dir.glob("*.pdf"))
    print(f"\nReports generated: {len(reports)}")
    for r in reports:
        print(f"  → {r}")


if __name__ == "__main__":
    asyncio.run(main())
