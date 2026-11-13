"""Platform-owned Git repositories; agents only see an isolated worktree."""

import os
import subprocess
from pathlib import Path
from uuid import UUID

from nexus.orchestration.contracts import Blocked
from nexus.services.artifacts import source_files


class Workspaces:
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def prepare(self, run_id: str) -> Path:
        key = str(UUID(run_id))
        base = self.root / key
        repository, tree = base / "repository", base / "worktree"
        if tree.exists():
            return tree
        base.mkdir(exist_ok=True)
        environment = {"PATH": os.defpath, "HOME": str(base), "GIT_CONFIG_NOSYSTEM": "1"}

        def git(*args):
            subprocess.run(
                ["git", "-c", "core.hooksPath=/dev/null", *args],
                check=True,
                capture_output=True,
                env=environment,
                timeout=30,
            )

        git("init", "--initial-branch=main", str(repository))
        git(
            "-C",
            str(repository),
            "-c",
            "user.name=NEXUS",
            "-c",
            "user.email=nexus@localhost",
            "commit",
            "--allow-empty",
            "-m",
            "Initialize isolated project",
        )
        git("-C", str(repository), "worktree", "add", "-b", f"run/{key}", str(tree))
        return tree

    def commit(self, workspace: str) -> dict:
        tree = Path(workspace).resolve()
        if not tree.is_relative_to(self.root) or tree.name != "worktree":
            raise Blocked("invalid_workspace")
        files = source_files(tree)  # Reject symlinks/devices/oversized output before host Git.
        if not files:
            raise Blocked("empty_workspace")
        metadata = tree.parent / "repository" / ".git" / "worktrees" / "worktree"
        environment = {"PATH": os.defpath, "HOME": str(tree.parent), "GIT_CONFIG_NOSYSTEM": "1"}

        def git(*args):
            return subprocess.run(
                [
                    "git",
                    f"--git-dir={metadata}",
                    f"--work-tree={tree}",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    *args,
                ],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
                timeout=30,
            ).stdout.strip()

        git("add", "--all")
        changed = git("diff", "--cached", "--name-only", "--no-ext-diff")
        git(
            "-c",
            "user.name=NEXUS",
            "-c",
            "user.email=nexus@localhost",
            "commit",
            "--allow-empty",
            "-m",
            "Agent implementation checkpoint",
        )
        return {"commit_sha": git("rev-parse", "HEAD"), "changed_files": changed.splitlines()}
