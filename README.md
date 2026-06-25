# mvp-pythonbdd

Turn **SafeZone QA acceptance criteria** into a **runnable behave feature** (authored by AI on AWS
Bedrock), drive it against an **already-confirmed integration chain**, and **print exactly what the run
would do in AWS** — as a human-readable summary and as JSON. The run makes **no** calls to Step
Functions or Athena: it *plans*, it does not perform.

This is the lean MVP distilled from the [ASP-1563 PoC](https://github.com/glm353/poc-pythonbdd), built
to the AI-driven tooling playbook (ASP-1575 / ASP-1586). The PoC already executed this chain **live on
dev** (all green) — so the plan this MVP prints is the real, verified sequence, not a guess.

## The pipeline

```
 acceptance-criteria/contractor-safezone.acs.txt        (Test Analyst: the "what", AC-NN / Given:When:Then)
            │
            ▼   author/author.py  ── loads skills/bdd-author/SKILL.md, calls Claude (Opus 4.x) on Bedrock
 features/contractor_safezone.feature  +  features/steps/contractor_steps.py   (generated; empty until you run it)
            │
            ▼   behave  ── drives mvp_bdd.ScenarioContext
 chains/beakon-contractor__safezone.json   (the confirmed chain; the When names ZERO processes —
            │                               the chain is figured out from each Then's target table)
            ▼   mvp_bdd/planner.py : PlanBackend  (records intended AWS actions instead of running them)
 PRINTED AWS EXECUTION PLAN  +  out/execution-plan.json
   seed mole → trigger each Step Functions process → run the Athena count=0=pass assertion → teardown
```

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

# (1) Verify the planner offline - NO AWS/Bedrock creds needed:
.venv/Scripts/python -m mvp_bdd.planner --selfcheck

# (2) AI-author the feature + steps from the ACs (needs Bedrock: Okta SSO + a profile/region):
.venv/Scripts/python author/author.py
.venv/Scripts/python -m behave --dry-run features/contractor_safezone.feature   # expect 0 undefined

# (3) Run it - prints the planned AWS execution and writes the JSON artifact (still NO live AWS calls):
.venv/Scripts/python -m behave features/contractor_safezone.feature
```

`features/` and `features/steps/` ship **empty** — step (2) fills them. That is the point: authoring is
a real, re-runnable step, not something pre-baked.

## What the plan looks like

Each scenario's run accumulates an ordered list of intended AWS actions:

```
[ 1] SEED   Athena INSERT -> "molecular_vms_beakon_dev"."contractor"  (5 rows)
[ 2] RUN    StepFunctions StartExecution  DataLoaderProcessId=domain-foundation-role-supplier  -> domain_foundation_role_dev.supplier (wait SUCCEEDED)
[ 3] RUN    StepFunctions StartExecution  DataLoaderProcessId=business-fm-safezone-supplier     -> business_fm_safezone_dev.supplier
[ 4] RUN    StepFunctions StartExecution  DataLoaderProcessId=business-fm-safezone-user         -> business_fm_safezone_dev.user
[ 5] RUN    StepFunctions StartExecution  DataLoaderProcessId=business-fm-safezone-user-group   -> business_fm_safezone_dev.user_group
[ 6] ASSERT Athena query on "business_fm_safezone_dev"."user_group"  [expected row present; 0 rows = pass]
        SELECT 'missing expected row in ...' AS failure WHERE NOT EXISTS (SELECT 1 FROM ... WHERE CAST("uon_user_id" AS varchar) = '...' AND ...)
 ...
[ N] TEARDOWN Athena DELETE -> ... (shared-dev hygiene)
```

The same content lands in **`out/execution-plan.json`** (`{disclaimer, platform, steps:[...]}`) for
downstream tooling.

> **Important:** this MVP *describes* the AWS calls; it does not make them. The resource ids (the
> common-sf state-machine ARN, Athena workgroup `dev3`, the "All Contractors" group id) were **observed
> in the live dev runs on 2026-06-18 / 06-22** (see the PoC's SESSION-NOTES). `boto3` is a dependency
> only because `author/author.py` calls **Bedrock**; the behave run uses no boto3.

## The one idea

**The `When` names zero processes.** The integration chain is resolved from two endpoints, both taken
from the scenario: the **source** from the Given (entity → `Beakon.contractor`) and the **target** from
the Then (the schema of the asserted table → `safezone`). Resolution is lazy — the chain is loaded and
walked on the **first Then**. See [CLAUDE.md](CLAUDE.md) and [WORKFLOW.md](WORKFLOW.md).

## Layout

| Path | What |
|---|---|
| [acceptance-criteria/](acceptance-criteria/) | The analyst's ACs (real `AC-NN` / Given:When:Then format) — the input |
| [skills/bdd-author/SKILL.md](skills/bdd-author/SKILL.md) | The authoring instruction fed to Bedrock |
| [author/](author/) | `author.py` (Bedrock call), `bedrock_config.py`, `environment.py.tmpl` |
| [chains/](chains/) | The committed, confirmed chain artifact (no generator) |
| [mvp_bdd/](mvp_bdd/) | The framework: derivation, chain load, assertion compile, ScenarioContext, **PlanBackend** |
| `features/` | **Generated** by `author.py`: the `.feature`, steps, and `environment.py` |
| `out/` | `execution-plan.json` (gitignored) |
