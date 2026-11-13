"""Deterministic tool/path policy independent of provider-generated instructions."""

from pathlib import Path

from nexus.tools.registry import TOOLS as TOOL_DEFINITIONS
from nexus.tools.registry import VALIDATORS, authorize

TOOLS = set(TOOL_DEFINITIONS)


def permitted(name: str, arguments: dict, root: Path) -> bool:
    try:
        authorize(name, {"project:read", "project:write"})
        VALIDATORS[name].model_validate(arguments)
    except (PermissionError, ValueError):
        return False
    root = root.resolve()
    location = (
        arguments.get("file_path")
        if name in {"Read", "Write", "Edit"}
        else arguments.get("path", str(root))
    )
    if not isinstance(location, str) or not location:
        return False
    path = Path(location)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        return False
    if any(part.startswith(".") for part in resolved.relative_to(root).parts):
        return False
    if name == "Glob":
        pattern = arguments.get("pattern", "")
        if not isinstance(pattern, str) or pattern.startswith("/") or ".." in Path(pattern).parts:
            return False
    return True
