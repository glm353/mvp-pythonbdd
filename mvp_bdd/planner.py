"""PlanBackend - describe the AWS execution instead of performing it.

This is the heart of the MVP. It implements the same four-method backend shape the PoC's live `aws`
backend implements (`seed` / `run_process` / `query` / `sql_table`), but **every method records an
intended AWS action into an ordered plan log instead of calling AWS**. After the run, the plan is
printed and written to ``out/execution-plan.json``.

It holds ZERO scenario knowledge. It only records what it is handed:
  * ``seed(table, rows)``      -> an Athena INSERT to land the source mole  (from the Given's rows)
  * ``run_process(meta)``      -> a Step Functions StartExecution           (from the chain JSON)
  * ``query(sql)``             -> an Athena assertion query                 (compiled from the Then)
All per-scenario specificity lives in the authored .feature and the chain JSON; swap either and the
plan changes with no code change here. The only constants below are genuine PLATFORM identifiers.

`query` returns ``[]`` so the count=0=pass assertions register as "would pass" - the planner describes
INTENT, it does not validate live data. (The PoC already proved these steps run green on dev:
SESSION-NOTES 2026-06-18 / 06-22.)
"""
from __future__ import annotations

import json
from pathlib import Path

from . import ENV_CODE, OUT_DIR
from .assertions import _sql_literal
from .derivation import schema_with_env, split_qualified

# --------------------------------------------------------------------------------------------------
# PLATFORM identifiers - OBSERVED in the live dev runs on 2026-06-18 / 2026-06-22 (see the PoC's
# SESSION-NOTES). They are printed so the plan is concrete; this MVP does NOT call them.
# --------------------------------------------------------------------------------------------------
AWS_REGION = "ap-southeast-2"
AWS_ACCOUNT = "484438948628"
COMMON_SF_ARN = f"arn:aws:states:{AWS_REGION}:{AWS_ACCOUNT}:stateMachine:uon-nonprod-common-sf-dev"
ATHENA_WORKGROUP = "dev3"
# The real molecular_fm_safezone.saf_group.id for display_name 'all contractors' (terminal join key).
ALL_CONTRACTORS_GROUP_ID = "3pbmvtme6yuufgz5iwcilu2qn4"

PLAN_PATH = OUT_DIR / "execution-plan.json"

_DISCLAIMER = (
    "PLANNED, NOT EXECUTED. Resource ids were OBSERVED in the live dev runs on 2026-06-18/06-22 "
    "(poc-pythonbdd SESSION-NOTES). This MVP prints the intended AWS calls; it makes none."
)


class PlanBackend:
    """Records the AWS actions a live run would take, in call order, as an inspectable plan."""

    def __init__(self, *, env_code: str = ENV_CODE):
        self.env_code = env_code
        self.steps: list[dict] = []
        self._seq = 0
        self._teardown_targets: list[str] = []   # qualified tables the chain wrote, for teardown

    # --- backend ABC shape ------------------------------------------------------------------------
    def sql_table(self, table_logical: str) -> str:
        """logical 'business_fm_safezone.user_group' -> quoted '"business_fm_safezone_dev"."user_group"'."""
        schema, table = split_qualified(table_logical)
        return f'"{schema_with_env(schema, self.env_code)}"."{table}"'

    def seed(self, table_logical: str, rows: list[dict]) -> None:
        target = self.sql_table(table_logical)
        self._record({
            "step": "seed",
            "service": "athena",
            "action": "StartQueryExecution",
            "workgroup": ATHENA_WORKGROUP,
            "target": target,
            "rows": len(rows),
            "sql": _render_insert(target, rows),
            "note": "land the source mole (the Given) via an Iceberg INSERT",
        })
        self._remember_teardown(target)

    def run_process(self, meta: dict) -> None:
        produces_logical = f'{meta["database_name"]}.{meta["silver_table"]}'
        self._record({
            "step": "run_process",
            "service": "stepfunctions",
            "action": "StartExecution",
            "state_machine_arn": COMMON_SF_ARN,
            "input": {"DataLoaderProcessId": meta["process_id"]},
            "wait_for": "SUCCEEDED",
            "produces": produces_logical,
            "process_type": meta.get("process_type"),
            "note": f"trigger the {meta.get('process_type')} process; wait for the Glue job to land "
                    f"{produces_logical}",
        })
        self._remember_teardown(f'"{meta["database_name"]}"."{meta["silver_table"]}"')

    def query(self, sql: str) -> list:
        kind = "expected row present" if "NOT EXISTS" in sql else "forbidden row absent"
        self._record({
            "step": "assert",
            "service": "athena",
            "action": "StartQueryExecution",
            "workgroup": ATHENA_WORKGROUP,
            "target": _table_from_assertion(sql),
            "asserts": kind,
            "expect": "0 rows = pass",
            "sql": sql,
            "note": "run the compiled count=0=pass assertion on Athena",
        })
        return []   # planner describes intent; no live data to return -> assertion 'would pass'

    def close(self) -> None:  # parity with the PoC backend ABC; nothing to release
        pass

    # --- teardown + dump --------------------------------------------------------------------------
    def plan_teardown(self) -> None:
        """Append the Iceberg DELETE steps that a shared-dev run would use to clean up its test rows."""
        for target in self._teardown_targets:
            self._record({
                "step": "teardown",
                "service": "athena",
                "action": "StartQueryExecution",
                "workgroup": ATHENA_WORKGROUP,
                "target": target,
                "sql": f"DELETE FROM {target}\nWHERE email LIKE 'bddpoc-%@mailinator.com'  "
                       f"-- or the run's traceable key",
                "note": "shared-dev hygiene: remove this run's seeded/derived rows",
            })

    def as_dict(self) -> dict:
        return {
            "disclaimer": _DISCLAIMER,
            "platform": {
                "region": AWS_REGION,
                "account": AWS_ACCOUNT,
                "common_state_machine_arn": COMMON_SF_ARN,
                "athena_workgroup": ATHENA_WORKGROUP,
                "all_contractors_group_id": ALL_CONTRACTORS_GROUP_ID,
            },
            "steps": self.steps,
        }

    # --- internals --------------------------------------------------------------------------------
    def _record(self, step: dict) -> dict:
        self._seq += 1
        step = {"seq": self._seq, **step}
        self.steps.append(step)
        return step

    def _remember_teardown(self, target: str) -> None:
        if target not in self._teardown_targets:
            self._teardown_targets.append(target)


# --- rendering helpers -----------------------------------------------------------------------------

def _render_insert(target: str, rows: list[dict]) -> str:
    """A representative Iceberg INSERT for the seeded mole rows (columns = union, ordered)."""
    if not rows:
        return f"INSERT INTO {target} DEFAULT VALUES  -- (no rows)"
    cols: list[str] = []
    for row in rows:
        for k in row:
            if k not in cols:
                cols.append(k)
    col_sql = ", ".join(f'"{c}"' for c in cols)
    value_lines = []
    for row in rows:
        vals = ", ".join(_sql_literal(row.get(c)) for c in cols)
        value_lines.append(f"  ({vals})")
    values_sql = ",\n".join(value_lines)
    return f"INSERT INTO {target} ({col_sql}) VALUES\n{values_sql}"


def _table_from_assertion(sql: str) -> str:
    """Pull the quoted table out of a compiled assertion's failure label (best-effort)."""
    head = sql.split("' AS failure", 1)[0]
    return head.split(" in ", 1)[1].strip() if " in " in head else "?"


# --- output ----------------------------------------------------------------------------------------

def print_plan(backend: PlanBackend) -> None:
    """Human-readable summary of the planned AWS execution."""
    line = "=" * 92
    print(f"\n{line}\nPLANNED AWS EXECUTION  ({_DISCLAIMER})\n{line}")
    for s in backend.steps:
        if s["step"] == "seed":
            head = f"SEED   Athena INSERT -> {s['target']}  ({s['rows']} rows)"
        elif s["step"] == "run_process":
            head = (f"RUN    StepFunctions StartExecution  DataLoaderProcessId={s['input']['DataLoaderProcessId']}"
                    f"  -> {s['produces']}  (wait {s['wait_for']})")
        elif s["step"] == "assert":
            head = f"ASSERT Athena query on {s['target']}  [{s['asserts']}; {s['expect']}]"
        else:
            head = f"TEARDOWN Athena DELETE -> {s['target']}"
        print(f"\n[{s['seq']:>2}] {head}")
        if s.get("sql"):
            for ln in s["sql"].splitlines():
                print(f"        {ln}")
    print(f"\n{line}")
    counts = {}
    for s in backend.steps:
        counts[s["step"]] = counts.get(s["step"], 0) + 1
    print("SUMMARY:", ", ".join(f"{k}={v}" for k, v in counts.items()), f"(total {len(backend.steps)})")
    print(line)


def dump_plan(backend: PlanBackend, path: Path = PLAN_PATH) -> Path:
    """Write the full plan as JSON; returns the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(backend.as_dict(), indent=2), encoding="utf-8")
    return path


# --- offline self-check (no AWS / Bedrock creds needed) --------------------------------------------

def selfcheck() -> int:
    """Drive a Core-4-shaped scenario through the planner end-to-end and validate the emitted plan.

    Exercises the real path: seed -> load committed chain -> walk it -> compile+record assertions ->
    teardown -> JSON. No network. Returns a process exit code.
    """
    from .assertions import assert_absent_row, assert_expected_row
    from .chain import load_chain, run_chain
    from .derivation import derive_source, derive_target_system

    backend = PlanBackend(env_code=ENV_CODE)
    src = derive_source("contractor")
    backend.seed(src.mole_table_logical(), [
        {"beakon_record_number": f"bddf0c00-0000-4000-8000-00000000000{i}",
         "primary_email_address": f"bddpoc-{i}@mailinator.com", "user_status": "Active"}
        for i in range(1, 6)
    ])
    target = derive_target_system(["business_fm_safezone.user_group"], ENV_CODE)
    chain = load_chain(src.anchor, target, env_code=ENV_CODE)
    ran = run_chain(backend, chain)
    assert_expected_row(backend, "business_fm_safezone.user_group", {
        "uon_user_id": "bddf0c00-0000-4000-8000-000000000001",
        "saf_group_id": ALL_CONTRACTORS_GROUP_ID,
    })
    assert_absent_row(backend, "business_fm_safezone.supplier",
                      {"supplier_id": "bddf0c00-0000-4000-8000-000000000005"})
    backend.plan_teardown()

    print_plan(backend)
    path = dump_plan(backend)
    print(f"\n[selfcheck] wrote {len(backend.steps)} steps to {path}")

    counts = {s["step"]: 0 for s in backend.steps}
    for s in backend.steps:
        counts[s["step"]] += 1
    json.loads(path.read_text(encoding="utf-8"))  # JSON round-trips
    ok = (counts.get("seed") == 1 and counts.get("run_process") == 4
          and counts.get("assert") == 2 and counts.get("teardown", 0) >= 1
          and ran == ["domain-foundation-role-supplier", "business-fm-safezone-supplier",
                      "business-fm-safezone-user", "business-fm-safezone-user-group"])
    print(f"[selfcheck] {'PASS' if ok else 'FAIL'} - {counts}")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--selfcheck" in sys.argv:
        sys.exit(selfcheck())
    print("usage: python -m mvp_bdd.planner --selfcheck")
