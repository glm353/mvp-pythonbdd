"""The Bedrock-backed bdd-author step: ACs -> behave feature + step bindings.

This is the "AI turns acceptance criteria into runnable tests" moment. It loads the bdd-author SKILL
as the model's instruction, feeds the analyst's AC file plus a context pack (the committed chain, the
exact step vocabulary, the ScenarioContext API), calls **Claude (Opus 4.x) on AWS Bedrock**, and writes
the generated files into the (empty-at-init) features/ folder. It also drops the deterministic
environment.py lifecycle template.

It does NOT touch Step Functions / Athena - that is the planner's (printed) concern. The only AWS call
here is the Bedrock Converse request.

Run:
    python author/author.py                 # author into features/ (refuses to overwrite)
    python author/author.py --force         # overwrite existing generated files
    python author/author.py --dry-run       # build + print the prompt, make NO Bedrock call

Auth: your normal AWS chain (Okta SSO / AWS_PROFILE). Config: author/bedrock_config.py (env vars).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import bedrock_config as cfg

REPO_ROOT = Path(__file__).resolve().parents[1]
ACS_FILE = REPO_ROOT / "acceptance-criteria" / "contractor-safezone.acs.txt"
SKILL_FILE = REPO_ROOT / "skills" / "bdd-author" / "SKILL.md"
CHAIN_FILE = REPO_ROOT / "chains" / "beakon-contractor__safezone.json"
SCENARIO_FILE = REPO_ROOT / "mvp_bdd" / "scenario.py"
ENV_TMPL = Path(__file__).resolve().parent / "environment.py.tmpl"

FEATURES_DIR = REPO_ROOT / "features"
FEATURE_OUT = FEATURES_DIR / "contractor_safezone.feature"
STEPS_OUT = FEATURES_DIR / "steps" / "contractor_steps.py"
ENV_OUT = FEATURES_DIR / "environment.py"


def build_prompt() -> tuple[str, str]:
    """Return (system, user) for the Converse call. The SKILL is the instruction; the rest is context."""
    system = SKILL_FILE.read_text(encoding="utf-8")
    acs = ACS_FILE.read_text(encoding="utf-8")
    chain = CHAIN_FILE.read_text(encoding="utf-8")
    scenario_api = SCENARIO_FILE.read_text(encoding="utf-8")

    user = f"""Author the runnable behave artifacts for the contractor MVP from the acceptance criteria
below, following the SKILL exactly.

OUTPUT CONTRACT (strict): reply with EXACTLY TWO fenced code blocks and nothing else of substance:
  1) a ```gherkin block = the complete features/contractor_safezone.feature
  2) a ```python  block = the complete features/steps/contractor_steps.py
The .feature must use a Background (seed the AC-00 sample table + `When the SafeZone integration runs`)
and one Scenario per AC-01..AC-04 with a `# SAF-...` comment. The step file must bind ONLY to the
ScenarioContext API shown below (thin wrappers; import `parse_kv_table` from `mvp_bdd.scenario`).

=== ACCEPTANCE CRITERIA (analyst input) ===
{acs}

=== COMMITTED CHAIN (target tables / terminal; the When auto-derives from the Then) ===
{chain}

=== ScenarioContext API the step file MUST call (mvp_bdd/scenario.py) ===
{scenario_api}
"""
    return system, user


def extract_blocks(text: str) -> tuple[str, str]:
    """Pull the gherkin feature + python steps out of the model's fenced code blocks."""
    blocks = re.findall(r"```[ \t]*([A-Za-z0-9_+-]*)[ \t]*\r?\n(.*?)```", text, re.DOTALL)
    feature = steps = None
    for lang, body in blocks:
        low = lang.lower()
        if feature is None and (low in ("gherkin", "feature", "cucumber") or body.lstrip().startswith("Feature:")):
            feature = body.strip("\n") + "\n"
        elif steps is None and (low in ("python", "py") or "behave" in body):
            steps = body.strip("\n") + "\n"
    if feature is None or steps is None:
        raise SystemExit(
            "Could not find both a feature and a steps block in the model output.\n"
            f"Found {len(blocks)} fenced block(s). Re-run, or inspect the raw response above."
        )
    return feature, steps


def call_bedrock(system: str, user: str) -> str:
    import boto3

    session = boto3.Session(profile_name=cfg.profile()) if cfg.profile() else boto3.Session()
    client = session.client("bedrock-runtime", region_name=cfg.region())
    model = cfg.model_id()
    print(f"[author] Bedrock Converse  model={model}  region={cfg.region()}  profile={cfg.profile() or '(default chain)'}")
    try:
        resp = client.converse(
            modelId=model,
            system=[{"text": system}],
            messages=[{"role": "user", "content": [{"text": user}]}],
            inferenceConfig={"maxTokens": cfg.max_tokens(), "temperature": 0.0},
        )
    except Exception as exc:  # noqa: BLE001 - surface a helpful hint for the common failures
        raise SystemExit(
            f"[author] Bedrock call failed: {exc}\n"
            "Hints: (1) refresh Okta SSO so credentials are valid; (2) confirm the model id is enabled "
            "in this account/region with:\n"
            "    aws bedrock list-inference-profiles --region ap-southeast-2 "
            "--query \"inferenceProfileSummaries[?contains(inferenceProfileId,'opus')].inferenceProfileId\"\n"
            "then set BDD_AUTHOR_BEDROCK_MODEL to a listed id."
        )
    return "".join(b.get("text", "") for b in resp["output"]["message"]["content"])


def write_outputs(feature: str, steps: str, *, force: bool) -> None:
    targets = [(FEATURE_OUT, feature), (STEPS_OUT, steps), (ENV_OUT, ENV_TMPL.read_text(encoding="utf-8"))]
    existing = [p for p, _ in targets if p.exists()]
    if existing and not force:
        raise SystemExit(
            "[author] refusing to overwrite existing generated files (use --force):\n  "
            + "\n  ".join(str(p) for p in existing)
        )
    for path, body in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        print(f"[author] wrote {path.relative_to(REPO_ROOT)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bedrock bdd-author: ACs -> behave feature + steps")
    ap.add_argument("--force", action="store_true", help="overwrite existing generated files")
    ap.add_argument("--dry-run", action="store_true", help="build + print the prompt; make NO Bedrock call")
    args = ap.parse_args(argv)

    system, user = build_prompt()
    if args.dry_run:
        print("=== SYSTEM (skill) ===\n" + system + "\n\n=== USER (prompt) ===\n" + user)
        print("\n[author] --dry-run: no Bedrock call made.")
        return 0

    raw = call_bedrock(system, user)
    feature, steps = extract_blocks(raw)
    write_outputs(feature, steps, force=args.force)
    print("\n[author] done. Next:\n"
          "    python -m behave --dry-run features/contractor_safezone.feature   # expect 0 undefined\n"
          "    python -m behave features/contractor_safezone.feature             # prints the AWS plan")
    return 0


if __name__ == "__main__":
    sys.exit(main())
