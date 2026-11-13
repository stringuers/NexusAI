"""Durable worker entry point: python -m nexus.workers.runtime [--once]."""

import argparse
import asyncio
import logging
import os

from langgraph.types import Command
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nexus.agents.live import LiveProviders
from nexus.orchestration.checkpoints import checkpoints
from nexus.orchestration.contracts import Blocked, LeaseLost
from nexus.orchestration.graph import build_graph
from nexus.services.artifacts import configured_objects
from nexus.services.execution import RunStore
from nexus.workers.queue import RunQueue
from nexus.workers.sandbox import DockerSandbox
from nexus.workers.workspace import Workspaces


async def execute(sessions, lease, providers, workspaces, objects, checkpointer):
    store = RunStore(sessions, lease)
    graph = build_graph(store, providers, objects, workspaces, checkpointer)
    context = await store.context()
    config = {
        "configurable": {"thread_id": f"{context['workspace_id']}:{lease.run_id}"},
        "recursion_limit": 50,
    }
    snapshot = await graph.aget_state(config)
    pending_interrupt = any(task.interrupts for task in snapshot.tasks)
    payload = (
        Command(resume=True)
        if pending_interrupt
        else None
        if snapshot.values
        else {"context": context}
    )
    result = await graph.ainvoke(payload, config, durability="sync")
    if result.get("__interrupt__"):
        await store.settle("awaiting_approval")
    else:
        await store.settle(result.get("outcome", "failed"))


async def guarded_execute(queue, sessions, lease, providers, workspaces, objects, saver):
    task = asyncio.create_task(execute(sessions, lease, providers, workspaces, objects, saver))
    ownership_lost = False

    async def monitor():
        nonlocal ownership_lost
        while not task.done():
            await asyncio.sleep(10)
            try:
                alive = await asyncio.wait_for(queue.heartbeat(lease), 5)
            except Exception:  # noqa: BLE001 — unavailable fencing must stop execution
                alive = False
            if not alive:
                ownership_lost = True
                task.cancel()
                return

    heartbeat = asyncio.create_task(monitor())
    try:
        await task
    except LeaseLost:
        pass
    except asyncio.CancelledError:
        if not ownership_lost:
            raise
    except Blocked as error:
        try:
            await RunStore(sessions, lease).settle("blocked", str(error))
        except LeaseLost:
            pass
    except Exception:  # noqa: BLE001 — isolate a failed job; never log raw provider errors
        try:
            await RunStore(sessions, lease).settle("failed", "workflow_execution_error")
        except LeaseLost:
            pass
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


async def main(once: bool):
    database = os.environ["DATABASE_URL"]
    engine = create_async_engine(database)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    root = os.getenv("NEXUS_WORKSPACE_ROOT", ".data/workspaces")
    workspaces = Workspaces(root)
    objects = configured_objects()
    queue = RunQueue(sessions)
    try:
        async with checkpoints(
            database, os.getenv("NEXUS_CHECKPOINT_PATH", ".data/checkpoints.db")
        ) as saver:

            async def reconcile():
                while True:
                    try:
                        await DockerSandbox(root).reconcile(sessions)
                    except Exception:  # noqa: BLE001 — no raw daemon/credential errors in logs
                        logging.getLogger("nexus.worker").warning(
                            "sandbox_reconciliation_unavailable"
                        )
                    await asyncio.sleep(15)

            janitor = asyncio.create_task(reconcile())
            while True:
                lease = await queue.claim()
                if lease:
                    providers = LiveProviders(DockerSandbox(root, lease=lease), workspaces)
                    await guarded_execute(
                        queue, sessions, lease, providers, workspaces, objects, saver
                    )
                if once:
                    break
                if lease is None:
                    await asyncio.sleep(2)
    finally:
        if "janitor" in locals():
            janitor.cancel()
            await asyncio.gather(janitor, return_exceptions=True)
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    asyncio.run(main(parser.parse_args().once))
