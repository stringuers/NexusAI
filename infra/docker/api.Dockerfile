FROM python:3.12-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY apps/api ./apps/api
COPY nexus ./nexus
COPY skills ./skills
COPY alembic.ini ./
RUN useradd --uid 1000 --create-home nexus
USER 1000:1000
ENV PATH=/app/.venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
