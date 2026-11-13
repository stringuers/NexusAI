"""Consume at most one run and record the honest execution-pipeline blocker."""

import asyncio
import json
import os

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.workers.queue import RunQueue


async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        queue = RunQueue(async_sessionmaker(engine, expire_on_commit=False))
        lease = await queue.claim()
        if lease is None:
            print(json.dumps({"status": "idle"}))
            return
        recorded = await queue.finish(lease, "blocked", "execution_pipeline_not_implemented")
        print(
            json.dumps({"run_id": lease.run_id, "status": "blocked" if recorded else "lease_lost"})
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
