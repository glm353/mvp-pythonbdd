"""The "When": resolve the *already-confirmed* process chain for a (source, target) and walk it.

The MVP does NOT invoke the process-chain-generator. It loads the committed chain artifact keyed by
source+target (a trimmed copy of a real generator run that we have already executed live on dev) and
walks it. ``run_chain`` hands each non-source process to the backend; for the PlanBackend that means
"record the Step Functions trigger I would fire", not "run SQL".
"""
from __future__ import annotations

import json

from . import CHAINS_DIR, ENV_CODE
from .derivation import chain_key


def load_chain(source_anchor: str, target_system: str, *, env_code: str = ENV_CODE) -> dict:
    """Load the committed chain artifact for source+target. No live generation in the MVP."""
    path = CHAINS_DIR / f"{chain_key(source_anchor, target_system)}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No committed chain for {source_anchor} -> {target_system} at {path}."
        )
    return json.loads(path.read_text())


def run_chain(backend, chain: dict) -> list[str]:
    """Walk the chain in execution order, handing each NON-source process to the backend.

    The molecular source/leaf is the mole the Given seeds (seeded, not triggered), so it is skipped.
    Every other process is one platform trigger - the backend decides what that means (the PlanBackend
    records a Step Functions StartExecution). Returns the pids handed over.
    """
    source_pid = chain.get("source", {}).get("process_id")
    ran: list[str] = []
    for pid in chain["execution_order"]:
        if pid == source_pid:
            continue  # the mole is seeded by the Given, not triggered
        backend.run_process(chain["processes"][pid])
        ran.append(pid)
    return ran
