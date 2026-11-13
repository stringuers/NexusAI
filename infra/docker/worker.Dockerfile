FROM node:22-bookworm-slim AS node
FROM python:3.12-slim-bookworm
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /opt/codex
COPY packages/codex-worker/package*.json ./
RUN npm ci --omit=dev
COPY packages/codex-worker/review.mjs packages/codex-worker/browser-qa.mjs ./
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
RUN node /opt/codex/node_modules/playwright/cli.js install --with-deps chromium
RUN pip install --no-cache-dir claude-agent-sdk==0.2.181
WORKDIR /opt/nexus
COPY nexus ./nexus
RUN useradd --uid 1000 --create-home worker
ENV PYTHONPATH=/opt/nexus PYTHONDONTWRITEBYTECODE=1
USER 1000:1000
ENTRYPOINT ["python", "-m", "nexus.workers.container_entry"]
