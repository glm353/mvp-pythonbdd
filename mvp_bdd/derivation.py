"""Derive the chain endpoints FROM THE SCENARIO - never hand-listed.

The ticket's key requirement: the "When" process chain "should not need to be defined manually, but
figured out from Scenario or Then". So:

* the **source** comes from the Given (the entity word + a fixture->mole-table registry), and
* the **target** comes from the Then (the schema of the table(s) the assertion names).

Together they form the key the committed chain artifact is resolved by. Nothing here enumerates
processes; that's already baked into the confirmed chain JSON (see chain.py).

Copied from poc-pythonbdd/bdd_poc/derivation.py (unchanged - it is runner- and backend-agnostic).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

from . import ENV_CODE, FIXTURES_DIR


@dataclass(frozen=True)
class SourceSpec:
    """A scenario source: the entity the Given seeds, and where its mole lives."""
    entity: str           # e.g. "contractor"
    anchor: str           # process-chain anchor, e.g. "Beakon.contractor"
    mole_schema: str      # logical schema (no env suffix), e.g. "molecular_vms_beakon"
    mole_table: str       # e.g. "contractor"

    def mole_table_logical(self) -> str:
        return f"{self.mole_schema}.{self.mole_table}"


# Registry: entity word (as it appears in a Given) -> where its mole is + the chain anchor.
# Extend this (student, staff, ...) to add scenarios; the rest of the MVP is entity-agnostic.
ENTITY_SOURCES: dict[str, SourceSpec] = {
    "contractor": SourceSpec(
        entity="contractor",
        anchor="Beakon.contractor",
        mole_schema="molecular_vms_beakon",
        mole_table="contractor",
    ),
}


def derive_source(given_text: str) -> SourceSpec:
    """Find the seeded entity in a Given step (its prose or the fixture name) -> a SourceSpec.

    Non-alphanumerics are normalised to spaces first so the entity is found in both
    'a new contractor is added' and 'test_contractor_01.json'.
    """
    text = re.sub(r"[^a-z0-9]+", " ", given_text.lower())
    for entity, spec in ENTITY_SOURCES.items():
        if re.search(rf"\b{re.escape(entity)}\b", text):
            return spec
    raise ValueError(
        f"Could not derive a source entity from Given text: {given_text!r}. "
        f"Known entities: {sorted(ENTITY_SOURCES)}"
    )


# --- table-name helpers (logical <-> env-qualified) -------------------------------------------------

def split_qualified(name: str) -> tuple[str, str]:
    schema, _, table = name.partition(".")
    if not table:
        raise ValueError(f"Expected a 'schema.table' name, got {name!r}")
    return schema, table


def schema_with_env(schema: str, env_code: str = ENV_CODE) -> str:
    """business_fm_safezone -> business_fm_safezone_dev (idempotent)."""
    suffix = f"_{env_code}"
    return schema if schema.endswith(suffix) else f"{schema}{suffix}"


def schema_without_env(schema: str, env_code: str = ENV_CODE) -> str:
    suffix = f"_{env_code}"
    return schema[: -len(suffix)] if schema.endswith(suffix) else schema


def system_of_table(name: str, env_code: str = ENV_CODE) -> str:
    """The target system token = last segment of the (env-stripped) schema.

    business_fm_safezone[_dev].user_group -> "safezone"; molecular_vms_beakon[_dev].contractor -> "beakon".
    """
    schema, _ = split_qualified(name)
    return schema_without_env(schema, env_code).split("_")[-1]


def chain_key(source_anchor: str, target_system: str) -> str:
    """beakon-contractor__safezone - the file name the committed chain artifact is stored under."""
    src = source_anchor.lower().replace(".", "-")
    return f"{src}__{target_system.lower()}"


def derive_target_system(then_tables: list[str], env_code: str = ENV_CODE) -> str:
    """Pick the target system from the Then's table name(s). Asserts they agree."""
    systems = {system_of_table(t, env_code) for t in then_tables}
    if len(systems) != 1:
        raise ValueError(f"Then tables span multiple/zero target systems: {systems} from {then_tables}")
    return systems.pop()


# --- fixtures --------------------------------------------------------------------------------------

def load_fixture(name: str) -> dict:
    """Load a Given/reference fixture JSON from fixtures/."""
    path = FIXTURES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")
    return json.loads(path.read_text())


def fixture_rows(name: str) -> list[dict]:
    """Normalise a fixture to a list of row dicts (drops _comment; supports {'rows': [...]})."""
    data = load_fixture(name)
    if isinstance(data, dict) and "rows" in data:
        return [_strip_comments(r) for r in data["rows"]]
    return [_strip_comments(data)]


def _strip_comments(row: dict) -> dict:
    return {k: v for k, v in row.items() if not k.startswith("_")}
