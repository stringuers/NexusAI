import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy.engine import make_url


@pytest.fixture
def orchestration_db(tmp_path):
    configured = os.getenv("NEXUS_TEST_DATABASE_URL")
    if configured:
        import psycopg
        from psycopg import sql

        admin = make_url(configured).set(drivername="postgresql")
        name = f"nexus_test_{uuid4().hex}"
        with psycopg.connect(admin.render_as_string(hide_password=False), autocommit=True) as conn:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        url = admin.set(drivername="postgresql+asyncpg", database=name).render_as_string(
            hide_password=False
        )
    else:
        url = f"sqlite+aiosqlite:///{tmp_path}/orchestration.db"
    try:
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check=True,
            env={**os.environ, "DATABASE_URL": url},
            capture_output=True,
        )
        yield url
    finally:
        if configured:
            with psycopg.connect(
                admin.render_as_string(hide_password=False), autocommit=True
            ) as conn:
                conn.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
