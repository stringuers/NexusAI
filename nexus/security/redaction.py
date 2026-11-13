import os
import re

SECRET_NAMES = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "KIMI_API_KEY",
    "MANUS_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "NEXUS_API_TOKEN",
    "NEXUS_N8N_SECRET",
)


def redact(value):
    if isinstance(value, str):
        result = re.sub(r"(?i)Bearer\s+[a-z0-9._~-]+", "Bearer [REDACTED]", value)
        for name in SECRET_NAMES:
            secret = os.getenv(name)
            if secret and len(secret) >= 8:
                result = result.replace(secret, "[REDACTED]")
        return result
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value
