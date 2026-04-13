"""Unit tests for narrative_extract.locate_sections — fixture-only."""

from __future__ import annotations

from pathlib import Path

from config import settings
from pipeline import narrative_extract as nx

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "pipeline"
    / "fixtures"
    / "hgv_delinquency_section.html"
)


def test_fixture_exists():
    assert FIXTURE.exists(), f"missing fixture: {FIXTURE}"


def test_locate_sections_finds_delinquency_in_fixture():
    html = FIXTURE.read_text()
    sections = nx.locate_sections(html)

    assert "delinquency" in sections, (
        f"expected 'delinquency' section; got {list(sections.keys())}"
    )
    excerpt = sections["delinquency"]
    # Excerpt must be non-empty and contain the triggering keyword.
    assert excerpt
    assert "delinqu" in excerpt.lower() or "past due" in excerpt.lower()


def test_excerpts_respect_char_cap():
    html = FIXTURE.read_text() * 20  # blow up the input to force a cap
    sections = nx.locate_sections(html)
    cap = settings.NARRATIVE_EXCERPT_CHAR_LIMIT
    for name, excerpt in sections.items():
        assert len(excerpt) <= cap, f"{name} excerpt exceeds cap ({len(excerpt)} > {cap})"


def test_locate_sections_also_picks_up_fico():
    html = FIXTURE.read_text()
    sections = nx.locate_sections(html)
    # The fixture contains a FICO table too.
    assert "fico" in sections
    assert "fico" in sections["fico"].lower()
