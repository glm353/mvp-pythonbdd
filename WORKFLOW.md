# BDD workflow — Test Analyst ↔ DevOps collaboration

How a SafeZone QA acceptance criterion becomes an **executable behave feature whose run prints the AWS
integration steps it would take**, and **who owns each step**. This MVP is deliberately a *collaboration
between two roles*, not one person's script.

## The two roles

| | **Test Analyst (QA)** | **DevOps / Automation Engineer** |
|---|---|---|
| Owns | the **what** — the behaviour to verify (the acceptance criteria) | the **how** — turning the AC into a runnable, plan-emitting test |
| Input | SafeZone QA stories (SAF-*) + Doc-003 implementation guides | the analyst's ACs + Doc-003 for the real schema |
| Output | acceptance criteria (`AC-NN` / Given:When:Then:AND); **sign-off** that the `.feature` captures them | the **`.feature`** + step definitions + the planner wiring + the printed plan |
| Writes the `.feature` / Python? | **No** (writes ACs, reviews features) | **Yes** |
| Decides behaviour? | **Yes** | No |

**The contract between them is the acceptance criterion.** The analyst writes the AC; DevOps (with the
`bdd-author` skill, run on Bedrock) translates it into a runnable `.feature` and reuses a consistent
**step vocabulary**, kept plain-English *precisely so the analyst can review it without reading Python*.

## What the real analyst ACs look like

Real `[QA] SAF` stories (e.g. **SAF-327**) carry numbered `## AC-NN` blocks, each:

```
## AC-02 Correct rows / primary keys
Given: I have the driving logic ... from the Implementation Guide [DRAFT] Doc-003 ...
When: I inspect the table in AWS Athena
Then: I expect one record per normalized email address ...
AND: I expect no duplicates in the primary key column `uon_user_id` & `email`
```

They are **data-QA ACs**: inspect the deployed Athena table, verify it against Doc-003. Some stories
(SAF-326) are just a Doc-003 link; some bugs (SAF-473 same-email, SAF-489 +615) are prose + SQL. The
selected, contractor-scoped ACs for this MVP live in
[acceptance-criteria/contractor-safezone.acs.txt](acceptance-criteria/contractor-safezone.acs.txt),
written in that real template.

## The pipeline

| Stage | Owner | Artifact |
|---|---|---|
| 1. QA story / AC (`AC-NN` Given:When:Then:AND) | Test Analyst | [acceptance-criteria/contractor-safezone.acs.txt](acceptance-criteria/contractor-safezone.acs.txt) |
| 2. AC → Gherkin `.feature` + steps (Bedrock bdd-author) | **DevOps** | `features/contractor_safezone.feature`, `features/steps/contractor_steps.py` (generated) |
| 3. Planner wiring (PlanBackend, seed-once/run-once) | DevOps | [mvp_bdd/](mvp_bdd/), generated `features/environment.py` |
| 4. Review the `.feature` captures the AC | Test Analyst | sign-off |
| 5. Run → print the AWS execution plan (+ JSON) | DevOps (analyst reviews) | `out/execution-plan.json` |
| 6. Traceability back to the SAF ticket | Shared | `# SAF-xxx` comments in the `.feature` |

The key property preserved end-to-end: **the `When` names zero processes**. The chain is auto-derived
from the Given (source) and the Then (target table); the analyst never lists integration processes.

## DevOps authors with AI — the `bdd-author` skill on Bedrock

Rather than hand-cranking the recipe each time, it's packaged as a **skill**
([skills/bdd-author/SKILL.md](skills/bdd-author/SKILL.md)) and run through **AWS Bedrock** by
[author/author.py](author/author.py): the skill is the model's instruction, the AC file is the input,
and the model emits the `.feature` + steps. The skill is grounded in the behave/Gherkin docs and
enforces the conventions (step vocabulary, real Doc-003 columns, `count=0=pass`, seed-once/run-once,
no `Rule`). The human stays in the loop: the AI drafts, DevOps validates `behave --dry-run`, the analyst
signs off.

## How to run

See [README.md](README.md). In short: `python author/author.py` (Bedrock authoring fills the empty
`features/`), then `behave` (prints the planned AWS execution + writes `out/execution-plan.json`). The
behave run makes **no** calls to Step Functions / Athena — it only PLANS.
