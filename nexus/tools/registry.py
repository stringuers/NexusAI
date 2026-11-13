"""Tools are server policy, never executable skill text or model-granted permissions."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FileInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    file_path: str = Field(min_length=1, max_length=1000)


class WriteInput(FileInput):
    content: str = Field(max_length=5 * 1024 * 1024)


class EditInput(FileInput):
    old_string: str = Field(max_length=5 * 1024 * 1024)
    new_string: str = Field(max_length=5 * 1024 * 1024)
    replace_all: bool = False


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="ignore")
    pattern: str = Field(min_length=1, max_length=1000)
    path: str = Field(default="/workspace", max_length=1000)


class FileOutput(BaseModel):
    success: bool
    summary: str


@dataclass(frozen=True)
class ToolDefinition:
    id: str
    permission: str
    side_effect: Literal["read", "workspace_write", "execution", "external"]
    timeout_seconds: int
    retry: Literal["never", "safe_read"]
    idempotency: str
    input_schema: dict
    output_schema: dict
    logging: str = "metadata_only_no_credentials_or_file_content"


VALIDATORS = {
    "Read": FileInput,
    "Write": WriteInput,
    "Edit": EditInput,
    "Glob": SearchInput,
    "Grep": SearchInput,
}
TOOLS = {
    name: ToolDefinition(
        name,
        "project:read" if name in {"Read", "Glob", "Grep"} else "project:write",
        "read" if name in {"Read", "Glob", "Grep"} else "workspace_write",
        30,
        "safe_read" if name in {"Read", "Glob", "Grep"} else "never",
        "run_stage_and_scoped_file_path",
        validator.model_json_schema(),
        FileOutput.model_json_schema(),
    )
    for name, validator in VALIDATORS.items()
}


def authorize(tool: str, permissions: set[str]) -> ToolDefinition:
    definition = TOOLS.get(tool)
    if definition is None or definition.permission not in permissions:
        raise PermissionError("Tool is outside execution policy")
    return definition
