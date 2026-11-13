"""Local Compose-only restore drill; never target a production database."""

import os
import subprocess
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

COMPOSE = ["docker", "compose", "-f", "infra/compose.yaml", "exec", "-T", "postgres"]
TABLES = ("projects", "tasks", "workflow_runs", "agent_executions", "approvals", "artifacts")


def main():
    from sqlalchemy.engine import make_url

    configured = make_url(os.environ["DATABASE_URL"])
    if (
        configured.host not in {"127.0.0.1", "localhost"}
        or configured.port != 55432
        or configured.database != "nexus"
        or configured.username != "nexus"
    ):
        raise ValueError("This restore drill only supports the dedicated local Compose database")
    root = Path(".data/backups")
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    backup = root / "verified-local.dump"
    result = subprocess.run(
        COMPOSE + ["pg_dump", "-U", "nexus", "-d", "nexus", "-Fc"],
        capture_output=True,
        check=True,
        timeout=60,
    )
    backup.write_bytes(result.stdout)
    backup.chmod(0o600)
    restored = "nexus_restore_" + uuid4().hex
    connection = os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    # Restore only into a new randomly named database, never overwrite the original.
    with psycopg.connect(connection, autocommit=True) as source:
        source.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored)))
        try:
            subprocess.run(
                COMPOSE + ["pg_restore", "-U", "nexus", "-d", restored],
                input=result.stdout,
                check=True,
                capture_output=True,
                timeout=60,
            )

            url = make_url(connection).set(database=restored).render_as_string(hide_password=False)
            with psycopg.connect(url) as target:
                for table in TABLES:
                    query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                    assert source.execute(query).fetchone() == target.execute(query).fetchone(), (
                        table
                    )
            print(
                f"Restore drill passed: {len(TABLES)} canonical tables verified; backup saved privately."
            )
        finally:
            source.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(restored))
            )


if __name__ == "__main__":
    main()
