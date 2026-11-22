"""Alembic migration smoke test using SQLite."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_alembic_upgrade_and_downgrade_on_sqlite(tmp_path: Path) -> None:
    database_path = (tmp_path / "migration.db").as_posix()
    url = f"sqlite+pysqlite:///{database_path}"

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)

    command.upgrade(config, "head")

    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {
            "users",
            "profiles",
            "user_equipment",
            "user_injuries",
            "consents",
            "user_roles",
            "audit_log",
            "plans",
            "plan_versions",
            "plan_days",
            "plan_exercises",
            "plan_shares",
            "workout_sessions",
            "workout_exercises",
            "set_logs",
            "client_mutations",
            "feedback",
            "unsafe_reports",
            "daily_metrics",
            "personal_records",
            "weekly_reviews",
            "trainer_profiles",
            "trainer_clients",
            "trainer_invitations",
            "access_grants",
            "plan_reviews",
            "trainer_comments",
        } <= tables

        user_columns = {column["name"] for column in inspector.get_columns("users")}
        assert {"auth_issuer", "auth_subject", "deletion_requested_at"} <= user_columns

        plan_columns = {column["name"] for column in inspector.get_columns("plans")}
        assert {"owner_user_id", "current_version", "revision", "idempotency_key"} <= plan_columns

        workout_columns = {
            column["name"] for column in inspector.get_columns("workout_sessions")
        }
        assert {
            "owner_user_id",
            "plan_id",
            "status",
            "total_sets",
            "client_session_id",
        } <= workout_columns

        role_indexes = {index["name"] for index in inspector.get_indexes("user_roles")}
        assert "uq_user_roles_user_role_platform" in role_indexes
    finally:
        engine.dispose()

    command.downgrade(config, "base")

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
        assert "users" not in tables
        assert "audit_log" not in tables
        assert "plans" not in tables
        assert "plan_shares" not in tables
        assert "workout_sessions" not in tables
        assert "set_logs" not in tables
        assert "feedback" not in tables
        assert "unsafe_reports" not in tables
        assert "daily_metrics" not in tables
        assert "personal_records" not in tables
        assert "weekly_reviews" not in tables
        assert "trainer_profiles" not in tables
        assert "trainer_clients" not in tables
    finally:
        engine.dispose()
