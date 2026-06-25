"""ScenarioContext - the framework-agnostic glue the behave step file drives.

Holds the per-scenario state and implements each Gherkin clause once, so the behave step file is a
thin wrapper. Crucially the chain is resolved LAZILY, from the first Then's target table - the literal
embodiment of the ticket's "figured out from ... Then": the When only signals intent; the process
chain isn't known until the Then names what it asserts on.

Adapted from poc-pythonbdd/bdd_poc/scenario.py: same lazy derivation, but the backend is always the
PlanBackend and the live-chain option is gone (the committed chain is the only source).
"""
from __future__ import annotations

from . import ENV_CODE
from .assertions import assert_absent_row, assert_expected_row
from .chain import load_chain, run_chain
from .derivation import (
    SourceSpec,
    derive_source,
    derive_target_system,
    fixture_rows,
    load_fixture,
)


class ScenarioContext:
    def __init__(self, backend, *, env_code: str = ENV_CODE):
        self.backend = backend
        self.env_code = env_code
        self.source: SourceSpec | None = None
        self.run_requested = False
        self.chain: dict | None = None
        self.executed_pids: list[str] = []
        self._seeded_rows: list[dict] = []   # idempotency guard for the seed-once flow

    # --- Given ------------------------------------------------------------------------------------
    def seed_reference(self, fixture_name: str, table_logical: str) -> None:
        self.backend.seed(table_logical, fixture_rows(fixture_name))

    def add_entity(self, fixture_name: str, given_text: str) -> None:
        """Derive the source from the Given text, then seed its mole from a single-row fixture."""
        self.source = derive_source(given_text)
        row = {k: v for k, v in load_fixture(fixture_name).items() if not k.startswith("_")}
        self.backend.seed(self.source.mole_table_logical(), [row])

    def add_entities(self, fixture_name: str, given_text: str) -> None:
        """Like add_entity, but seed MANY mole rows from a ``{"rows": [...]}`` fixture."""
        self.source = derive_source(given_text)
        self.backend.seed(self.source.mole_table_logical(), fixture_rows(fixture_name))

    def add_contractor_rows(self, rows: list[dict], given_text: str,
                            template_fixture: str | None = None) -> None:
        """Seed MANY mole rows from explicit row dicts (a Gherkin data table), each merged over an
        optional template fixture so the analyst only spells out the columns that matter.

        Idempotent: ONE feature-scoped context seeds the whole test population once, then every
        scenario asserts against the single chain walk. Repeated calls (behave re-runs Background per
        scenario) are no-ops.
        """
        if self._seeded_rows:
            return
        self.source = derive_source(given_text)
        template = {}
        if template_fixture:
            template = {k: v for k, v in load_fixture(template_fixture).items()
                        if not k.startswith("_")}
        merged = [{**template, **row} for row in rows]
        self.backend.seed(self.source.mole_table_logical(), merged)
        self._seeded_rows = merged

    # --- When -------------------------------------------------------------------------------------
    def request_run(self) -> None:
        if self.source is None:
            raise AssertionError("When ran before any Given seeded a source entity")
        self.run_requested = True

    # --- Then -------------------------------------------------------------------------------------
    def _ensure_chain_run(self, then_table: str) -> None:
        if not self.run_requested:
            raise AssertionError("Then reached before the When step requested the integration run")
        if self.chain is None:
            target_system = derive_target_system([then_table], self.env_code)
            self.chain = load_chain(self.source.anchor, target_system, env_code=self.env_code)
            self.executed_pids = run_chain(self.backend, self.chain)

    def assert_table_row(self, table_logical: str, expected: dict) -> None:
        self._ensure_chain_run(table_logical)
        assert_expected_row(self.backend, table_logical, expected)

    def assert_table_no_row(self, table_logical: str, forbidden: dict) -> None:
        """Then-side of an exclusion: a rejected/dropped row must be absent."""
        self._ensure_chain_run(table_logical)
        assert_absent_row(self.backend, table_logical, forbidden)

    def assert_terminal(self, expected_terminal: str) -> None:
        if self.chain is None:
            raise AssertionError("No chain has been resolved yet (assert a table row first)")
        terminals = self.chain.get("terminals", [])
        assert expected_terminal in terminals, (
            f"Auto-derived chain terminals {terminals} do not include the gotcha terminal "
            f"{expected_terminal!r}. Execution order was: {self.chain.get('execution_order')}"
        )


def parse_kv_table(rows: list[list[str]]) -> dict:
    """Turn a vertical | column | value | DataTable (header + rows) into a dict."""
    if not rows:
        return {}
    body = rows[1:] if rows and [c.lower() for c in rows[0]] == ["column", "value"] else rows
    return {r[0]: r[1] for r in body}
