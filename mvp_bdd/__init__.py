"""mvp_bdd - framework-agnostic core for the AC -> feature -> known-chain -> printed-AWS-plan MVP.

The behave step file (features/steps/, authored by author/author.py) is a thin wrapper over this
package, so the Gherkin->plan logic lives in exactly one place. See README.md / CLAUDE.md.

Distilled from poc-pythonbdd's bdd_poc: same derivation + assertion compilation, but the live
execution backend is replaced by a PlanBackend that *describes* the AWS steps instead of running them,
and the process-chain-generator path is dropped (we use the committed, already-confirmed chain).
"""
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
REPO_ROOT = PKG_DIR.parent
CHAINS_DIR = REPO_ROOT / "chains"
FIXTURES_DIR = REPO_ROOT / "fixtures"
OUT_DIR = REPO_ROOT / "out"

# The MVP targets the dev deploy environment (db-name suffix), matching the committed chain artifact.
ENV_CODE = "dev"
