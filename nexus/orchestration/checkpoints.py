from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from sqlalchemy.engine import make_url


@asynccontextmanager
async def checkpoints(database_url: str, sqlite_path: str = ".data/checkpoints.db"):
    url = make_url(database_url)
    if url.get_backend_name() == "postgresql":
        connection = url.set(drivername="postgresql").render_as_string(hide_password=False)
        async with AsyncPostgresSaver.from_conn_string(connection) as saver:
            await saver.setup()
            yield saver
    elif url.get_backend_name() == "sqlite":
        # Local development/tests only. PostgreSQL remains the production backend.
        from pathlib import Path

        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(sqlite_path) as saver:
            yield saver
    else:
        raise ValueError("Unsupported checkpoint backend")
