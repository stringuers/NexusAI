import os

DEFINITIONS = [
    ("openai", "OpenAI Planner", "openai", ["planning"], "NEXUS_PLANNER_MODEL", "OPENAI_API_KEY"),
    (
        "claude",
        "Claude Developer",
        "anthropic",
        ["development"],
        "NEXUS_CLAUDE_MODEL",
        "ANTHROPIC_API_KEY",
    ),
    ("codex", "Codex Reviewer", "openai", ["review"], "NEXUS_CODEX_MODEL", "OPENAI_API_KEY"),
    (
        "gemini",
        "Gemini Visual Intelligence",
        "google",
        ["visual_analysis"],
        "NEXUS_GEMINI_MODEL",
        "GEMINI_API_KEY",
    ),
    ("kimi", "Kimi Research", "moonshot", ["research"], "NEXUS_KIMI_MODEL", "KIMI_API_KEY"),
    ("manus", "Manus External Tasks", "manus", ["external_tasks"], "", "MANUS_API_KEY"),
    ("hermes", "Hermes Skill Review", "hermes", ["skill_proposals"], "", "HERMES_ENDPOINT"),
]


def agents():
    output = []
    for key, name, provider, capabilities, model_env, secret_env in DEFINITIONS:
        implemented = key in {"openai", "claude", "codex", "gemini", "kimi"}
        configured = bool(os.getenv(secret_env) and (not model_env or os.getenv(model_env)))
        output.append(
            {
                "id": key,
                "name": name,
                "provider": provider,
                "capabilities": capabilities,
                "model": os.getenv(model_env) if model_env else None,
                "configuration_status": "configured" if configured else "not_configured",
                "implementation_status": "implemented" if implemented else "not_implemented",
                "health": "not_checked",
                "max_concurrency": 1,
                "timeout_seconds": 600,
                "allowed_tools": ["Read", "Write", "Edit", "Glob", "Grep"]
                if key == "claude"
                else ["read_only_repository"]
                if key == "codex"
                else [],
            }
        )
    return output
