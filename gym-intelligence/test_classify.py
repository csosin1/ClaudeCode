"""Unit tests for classify.py — specifically the reclassify_unknown pass
that adds OSM-generic filtering, ownership_type, and web_search-enabled
classification of chains stuck at 'unknown'.

Run with:  python -m unittest gym-intelligence/test_classify.py
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import classify  # noqa: E402
import db  # noqa: E402


def _fresh_db() -> str:
    """Create a tmp sqlite DB with the current schema and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db.init_db(path)
    return path


def _insert_chain(path: str, name: str, location_count: int = 10,
                  classification: str = "unknown") -> int:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        "INSERT INTO chains (canonical_name, competitive_classification, "
        "location_count, manually_reviewed) VALUES (?, ?, ?, 0)",
        (name, classification, location_count),
    )
    conn.commit()
    chain_id = cur.lastrowid
    conn.close()
    return chain_id


class TestOSMGenericFilter(unittest.TestCase):
    """OSM-generic names should short-circuit to 'not_a_chain' without
    ever hitting the Claude API."""

    def setUp(self):
        self.db_path = _fresh_db()

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def _run_with_exploding_client(self, names):
        """Run reclassify_unknown with a client that RAISES if called —
        proves the OSM generics short-circuit never hits the API."""
        for n in names:
            _insert_chain(self.db_path, n, location_count=50)

        client = MagicMock()
        client.messages.create.side_effect = AssertionError(
            "Claude API must NOT be called for OSM-generic names"
        )

        conn = db.get_connection(self.db_path)
        try:
            stats = classify.reclassify_unknown(conn, client)
        finally:
            conn.close()
        return stats

    def test_known_generics_marked_not_a_chain(self):
        names = ["Sporthalle", "Turnhalle", "Gimnasio", "Poliesportiu"]
        stats = self._run_with_exploding_client(names)
        self.assertEqual(stats["osm_generics_filtered"], 4)
        self.assertEqual(stats["chains_reclassified"], 4)
        self.assertEqual(stats["api_calls"], 0)
        self.assertEqual(stats["by_classification"].get("not_a_chain"), 4)

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT canonical_name, competitive_classification, ownership_type, "
            "ai_classification_rationale FROM chains"
        ).fetchall()
        conn.close()
        for row in rows:
            self.assertEqual(row["competitive_classification"], "not_a_chain")
            self.assertEqual(row["ownership_type"], "unknown")
            self.assertIn("OSM generic", row["ai_classification_rationale"] or "")

    def test_case_insensitive_match(self):
        # Lowercase, uppercase, mixed — all should match.
        self._run_with_exploding_client(["sporthalle", "SPORTHALLE", "SpOrThAlLe"])

    def test_ambiguous_names_not_filtered(self):
        """'The Gym' is NOT in the generic list (it IS a real UK chain).
        It must NOT be short-circuited — must call Claude."""
        _insert_chain(self.db_path, "The Gym", location_count=23)

        # Client that returns a minimal valid response.
        fake_response = SimpleNamespace(
            content=[SimpleNamespace(
                type="text",
                text='{"competitive_classification":"direct_competitor",'
                     '"ownership_type":"private","price_tier":"budget",'
                     '"normalized_18mo_cost":350,"membership_model":"flexible",'
                     '"pricing_notes":"~£20/mo","rationale":"UK budget chain."}',
            )],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
        )
        client = MagicMock()
        client.messages.create.return_value = fake_response

        conn = db.get_connection(self.db_path)
        try:
            stats = classify.reclassify_unknown(conn, client)
        finally:
            conn.close()

        self.assertEqual(stats["osm_generics_filtered"], 0)
        self.assertEqual(stats["api_calls"], 1)
        self.assertEqual(stats["tokens_input"], 1000)
        self.assertEqual(stats["tokens_output"], 200)
        self.assertGreater(stats["cost_usd"], 0)


class TestResponseParser(unittest.TestCase):
    """The web_search-enabled response interleaves tool_use + tool_result
    blocks before the final text block. The parser must walk content and
    grab the last text block."""

    def test_extracts_final_text_after_tool_blocks(self):
        response = SimpleNamespace(content=[
            SimpleNamespace(type="tool_use", id="srvtu_1", name="web_search",
                            input={"query": "foo gym chain pricing"}),
            SimpleNamespace(type="tool_result", tool_use_id="srvtu_1",
                            content=[{"type": "text", "text": "search results..."}]),
            SimpleNamespace(type="text", text='  {"competitive_classification":"direct_competitor","ownership_type":"public","price_tier":"budget","normalized_18mo_cost":300,"membership_model":"flexible","pricing_notes":"ok","rationale":"municipal"}  '),
        ])
        text = classify._extract_text_from_response(response)
        self.assertIn("direct_competitor", text)
        parsed = classify._parse_json_body(text)
        self.assertEqual(parsed["competitive_classification"], "direct_competitor")
        self.assertEqual(parsed["ownership_type"], "public")

    def test_strips_markdown_code_fences(self):
        fenced = "```json\n{\"competitive_classification\":\"unknown\",\"ownership_type\":\"unknown\"}\n```"
        parsed = classify._parse_json_body(fenced)
        self.assertEqual(parsed["competitive_classification"], "unknown")

    def test_extracts_json_from_noisy_text(self):
        noisy = 'Based on my research, here is the answer: {"competitive_classification":"non_competitor","ownership_type":"private"}'
        parsed = classify._parse_json_body(noisy)
        self.assertEqual(parsed["competitive_classification"], "non_competitor")


class TestSchemaMigration(unittest.TestCase):
    """init_db must be idempotent AND must allow the new 'not_a_chain'
    value after migration (i.e. the legacy CHECK must be gone)."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_init_db_is_idempotent(self):
        db.init_db(self.db_path)
        db.init_db(self.db_path)
        db.init_db(self.db_path)  # thrice, just to be sure
        # Column present?
        conn = sqlite3.connect(self.db_path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(chains)").fetchall()]
        conn.close()
        self.assertIn("ownership_type", cols)

    def test_not_a_chain_value_is_accepted(self):
        db.init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        # Must NOT raise a CHECK constraint violation.
        conn.execute(
            "INSERT INTO chains (canonical_name, competitive_classification) "
            "VALUES (?, 'not_a_chain')",
            ("Sporthalle",),
        )
        conn.commit()
        row = conn.execute(
            "SELECT competitive_classification FROM chains WHERE canonical_name='Sporthalle'"
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], "not_a_chain")

    def test_migrates_legacy_table_with_check_constraint(self):
        """Simulate an old DB built with the CHECK constraint and assert
        init_db upgrades it without losing rows."""
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE chains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                canonical_name TEXT UNIQUE NOT NULL,
                competitive_classification TEXT DEFAULT 'unknown'
                    CHECK(competitive_classification IN ('direct_competitor','non_competitor','unknown')),
                price_tier TEXT DEFAULT 'unknown'
                    CHECK(price_tier IN ('budget','mid_market','premium','unknown')),
                pricing_notes TEXT,
                normalized_18mo_cost REAL,
                membership_model TEXT DEFAULT 'unknown'
                    CHECK(membership_model IN ('commitment','flexible','mixed','unknown')),
                ai_classification_rationale TEXT,
                manually_reviewed INTEGER DEFAULT 0,
                location_count INTEGER DEFAULT 0,
                last_classified_date TEXT
            );
        """)
        conn.execute(
            "INSERT INTO chains (canonical_name, competitive_classification, "
            "location_count) VALUES ('Basic-Fit', 'direct_competitor', 1200)"
        )
        conn.commit()
        conn.close()

        db.init_db(self.db_path)  # should rebuild chains and preserve the row

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT canonical_name, competitive_classification, location_count, ownership_type "
            "FROM chains WHERE canonical_name='Basic-Fit'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["competitive_classification"], "direct_competitor")
        self.assertEqual(row["location_count"], 1200)
        self.assertEqual(row["ownership_type"], "unknown")

        # And the CHECK should be gone — inserting not_a_chain must work.
        conn.execute(
            "INSERT INTO chains (canonical_name, competitive_classification) "
            "VALUES ('Turnhalle', 'not_a_chain')"
        )
        conn.commit()
        conn.close()


class TestDryRun(unittest.TestCase):
    """Dry-run must not touch the DB or call the API."""

    def setUp(self):
        self.db_path = _fresh_db()
        _insert_chain(self.db_path, "Sporthalle", location_count=66)
        _insert_chain(self.db_path, "L'Appart Fitness", location_count=52)

    def tearDown(self):
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def test_dry_run_returns_plan_without_side_effects(self):
        client = MagicMock()
        client.messages.create.side_effect = AssertionError(
            "dry_run must not call the API"
        )

        conn = db.get_connection(self.db_path)
        try:
            plan = classify.reclassify_unknown(conn, client, dry_run=True)
        finally:
            conn.close()

        self.assertTrue(plan["dry_run"])
        self.assertEqual(plan["chains_planned"], 2)
        self.assertEqual(plan["osm_generics_would_skip"], 1)
        actions = {p["canonical_name"]: p["action"] for p in plan["plan"]}
        self.assertEqual(actions["Sporthalle"], "mark_not_a_chain")
        self.assertEqual(actions["L'Appart Fitness"], "call_claude_with_websearch")

        # DB unchanged.
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT competitive_classification FROM chains"
        ).fetchall()
        conn.close()
        self.assertTrue(all(r[0] == "unknown" for r in rows))


if __name__ == "__main__":
    unittest.main()
