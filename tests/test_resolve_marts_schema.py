"""Tests for scripts/generate_alert_report.py's resolve_marts_schema().

This is the fix for a real bug that shipped and only broke in GitHub
Actions: fetch_late_adjustments()/fetch_volume_anomalies() hardcoded
`analytics_marts` (the dev-target schema name), but reliability-demo.yml
only ever builds `ci` (`analytics_ci_marts`) — see the README's "Bugs
this caught" and docs/incidents/. Needs a reachable Postgres (the same
one docker-compose / CI provides) and is skipped automatically if one
isn't available. Runs against two throwaway schemas
(MARTS_SCHEMAS is monkeypatched to point at them), not the real
analytics_marts/analytics_ci_marts — this test drops and recreates its
schemas on every run, which would be destructive against real dev state.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from scripts import generate_alert_report
from scripts.ingest import get_engine

SCHEMA_A = "resolve_marts_schema_test_a"
SCHEMA_B = "resolve_marts_schema_test_b"


def _postgres_reachable() -> bool:
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable — run `docker compose up -d` first",
)


@pytest.fixture
def engine() -> Engine:
    return get_engine()


@pytest.fixture(autouse=True)
def _isolated_schemas(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(generate_alert_report, "MARTS_SCHEMAS", (SCHEMA_A, SCHEMA_B))
    with engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA_A} cascade"))
        conn.execute(text(f"drop schema if exists {SCHEMA_B} cascade"))
        conn.execute(text(f"create schema {SCHEMA_A}"))
        conn.execute(text(f"create schema {SCHEMA_B}"))
    yield
    with engine.begin() as conn:
        conn.execute(text(f"drop schema if exists {SCHEMA_A} cascade"))
        conn.execute(text(f"drop schema if exists {SCHEMA_B} cascade"))


def test_prefers_the_first_schema_when_both_have_the_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"create table {SCHEMA_A}.widgets (id int)"))
        conn.execute(text(f"create table {SCHEMA_B}.widgets (id int)"))

    assert generate_alert_report.resolve_marts_schema(engine, "widgets") == SCHEMA_A


def test_falls_back_to_the_second_schema_when_only_it_has_the_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"create table {SCHEMA_B}.widgets (id int)"))

    assert generate_alert_report.resolve_marts_schema(engine, "widgets") == SCHEMA_B


def test_returns_none_when_neither_schema_has_the_table(engine: Engine) -> None:
    assert generate_alert_report.resolve_marts_schema(engine, "widgets") is None
