"""Compile the Then's declared expected rows into assertion SQL - no pre-written QA SQL.

The Gherkin Then carries the expected values (per the ticket: ``Then table_X has new row with
{...}``). We compile each expected row into a check in the ASP-383 convention: the query states the
*failing* case ("this expected row is absent") and returns **0 rows on pass**. In this MVP the compiled
SQL is what the planner PRINTS as the Athena assertion it would run; in the PoC the same SQL ran live
against Athena (and could be cross-checked against SAF-187's hand-written queries / SAF-502's DQDL).

Copied verbatim from poc-pythonbdd/bdd_poc/assertions.py - the compiled SQL is exactly the assertion
string the plan emits.
"""
from __future__ import annotations

from dataclasses import dataclass


def _sql_literal(value) -> str:
    """Render a DataTable cell (always a string) or a Python scalar as a SQL literal.

    'true'/'false'/'null' (case-insensitive) get special handling; everything else is a string
    literal (the silver columns we assert on are VARCHAR), so no type-mismatch surprises.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value).strip()
    low = s.lower()
    if low == "null":
        return "NULL"
    if low in ("true", "false"):
        return low.upper()
    return "'" + s.replace("'", "''") + "'"


def _render_condition(col: str, value) -> str:
    """One column predicate for the assertion WHERE clause.

    NULL -> ``"col" IS NULL``; booleans -> ``"col" = TRUE/FALSE``. For everything else, compare the
    column CAST to varchar against the (string) literal, so a real typed column (e.g. an INTEGER like
    ``no_of_sources`` on Athena) doesn't raise ``integer = varchar`` TYPE_MISMATCH - and digit strings
    keep their leading zeros (``mobile_original``).
    """
    lit = _sql_literal(value)
    if lit == "NULL":
        return f'"{col}" IS NULL'
    if lit in ("TRUE", "FALSE"):
        return f'"{col}" = {lit}'
    return f'CAST("{col}" AS varchar) = {lit}'


def compile_expectation(table_sql: str, expected: dict) -> str:
    """Build a count=0=pass assertion: 'expected row is absent' returns 1 row, else 0 rows."""
    conds = [_render_condition(col, val) for col, val in expected.items()]
    where = " AND ".join(conds) if conds else "TRUE"
    label = "missing expected row in " + table_sql
    return (
        f"SELECT {_sql_literal(label)} AS failure\n"
        f"WHERE NOT EXISTS (\n"
        f"    SELECT 1 FROM {table_sql} WHERE {where}\n"
        f")"
    )


def compile_rejection(table_sql: str, forbidden: dict) -> str:
    """Build the mirror of ``compile_expectation``: a row that must be ABSENT.

    Used for the exclusion case (SAF-489 dropped number stays out / inactive contractor never reaches
    the terminal). Keeps the count=0=pass convention: the forbidden row being *present* returns a row
    (== failure); absent returns 0 rows (== pass).
    """
    conds = [_render_condition(col, val) for col, val in forbidden.items()]
    where = " AND ".join(conds) if conds else "TRUE"
    label = "forbidden row present in " + table_sql
    return (
        f"SELECT {_sql_literal(label)} AS failure\n"
        f"FROM {table_sql}\n"
        f"WHERE {where}"
    )


@dataclass
class AssertionFailure:
    table: str
    expected: dict
    sql: str


def assert_expected_row(backend, table_logical: str, expected: dict) -> None:
    """Run the compiled assertion against the backend; raise AssertionError on >0 rows."""
    table_sql = backend.sql_table(table_logical)
    sql = compile_expectation(table_sql, expected)
    rows = backend.query(sql)
    if rows:  # ASP-383: any returned row == failure
        raise AssertionError(
            f"Then failed - expected row not found in {table_logical}: {expected}\n"
            f"Compiled assertion (count=0=pass):\n{sql}"
        )


def assert_absent_row(backend, table_logical: str, forbidden: dict) -> None:
    """Run the rejection assertion; raise AssertionError if the forbidden row IS present."""
    table_sql = backend.sql_table(table_logical)
    sql = compile_rejection(table_sql, forbidden)
    rows = backend.query(sql)
    if rows:  # the forbidden row reached the table == failure
        raise AssertionError(
            f"Then failed - forbidden row found in {table_logical}: {forbidden}\n"
            f"Compiled assertion (count=0=pass):\n{sql}"
        )
