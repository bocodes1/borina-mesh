"""Daily-brief parser + generation (spec §8 / §10b)."""
from fastapi.testclient import TestClient

from main import app
from daily_brief import parse_brief, sections_for, SECTION_IDS

client = TestClient(app)

SAMPLE = """# Daily Brief — 2026-06-02

<section id="tldr">
- Markets calm; one earnings call at 4pm.
</section>

<section id="markets">
SPX flat overnight.
</section>

<section id="watchlist_movers">
NVDA +2% on supply news.
</section>

<section id="trading">
Polymarket bot healthy, edge 3%.
</section>

<section id="calendar">
09:00 Standup.
</section>

<section id="tasks_focus">
- Ship the rebuild.
</section>

<section id="inbox">
2 emails need a reply.
</section>

<section id="nudges">
- Review watchlist · run agent researcher
</section>

<section id="weather_logistics">
Sunny, 72° — light jacket.
</section>
"""


def test_parser_splits_all_sections():
    sections = parse_brief(SAMPLE)
    for sid in SECTION_IDS:
        assert sid in sections, f"missing section {sid}"
    assert "earnings call" in sections["tldr"]
    assert "NVDA" in sections["watchlist_movers"]


def test_each_tab_gets_its_sections(tmp_path, monkeypatch):
    # Write a sample brief into today's reports dir, then check section routing.
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    from daily_brief import save_brief

    save_brief(SAMPLE)

    finance = sections_for(None, ["markets", "watchlist_movers", "trading"])
    daily = sections_for(None, ["tldr", "tasks_focus", "nudges", "weather_logistics"])
    calendar = sections_for(None, ["calendar"])

    assert all(v is not None for v in finance.values())
    assert all(v is not None for v in daily.values())
    assert calendar["calendar"] and "Standup" in calendar["calendar"]


def test_manual_generate_writes_parseable_brief(tmp_path, monkeypatch):
    # Fallback (no LLM) must always write a full, parseable 9-section brief.
    monkeypatch.setenv("REPORTS_DIR", str(tmp_path))
    r = client.post("/daily/generate", params={"use_agent": False})
    assert r.status_code == 201, r.text
    found = r.json()["sections_found"]
    assert set(found) == set(SECTION_IDS)

    # And the three tabs can now read their sections.
    brief = client.get("/daily/brief").json()
    assert brief["exists"] is True
    summary = client.get("/daily/summary").json()
    assert summary["has_brief"] is True
