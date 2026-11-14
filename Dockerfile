FROM node:24.6.0-bookworm-slim AS web-build
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
# Required PR CI runs lint/types. Package the same locked source without
# repeating those checks or invalidating this layer for browser-test/doc edits.
COPY frontend/index.html frontend/vite.config.ts frontend/tsconfig.json ./
COPY frontend/src/ ./src/
COPY frontend/public/ ./public/
RUN npm exec -- vite build

FROM python:3.12.12-slim-bookworm AS api-build
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv export --locked --no-dev --prune torch --prune sentence-transformers --no-emit-project -o /tmp/requirements.txt && \
    uv venv && uv pip sync --require-hashes /tmp/requirements.txt
COPY src/ src/
RUN uv pip install --no-deps -e .

FROM python:3.12.12-slim-bookworm AS runtime
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd -g 10001 aimo && useradd -u 10001 -g aimo -M aimo
COPY src/ /app/src/
COPY migrations/ /app/migrations/
USER 10001:10001
ENTRYPOINT ["aimo"]

# Independent HTTP API image: no browser assets, model weights or ML dependencies.
FROM runtime AS api
COPY --from=api-build /app/.venv /app/.venv
EXPOSE 8000
CMD ["serve"]

FROM python:3.12.12-slim-bookworm AS worker-build
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy HF_HOME=/opt/aimo-model
COPY pyproject.toml uv.lock ./
ARG LOCAL_EMBEDDINGS=false
RUN if [ "$LOCAL_EMBEDDINGS" = "true" ]; then uv sync --frozen --no-dev --no-install-project; \
    else uv export --locked --no-dev --prune torch --prune sentence-transformers --no-emit-project -o /tmp/requirements.txt && \
    uv venv && uv pip sync --require-hashes /tmp/requirements.txt; fi
COPY src/aimo/model_spec.py /tmp/model_spec.py
RUN mkdir -p /opt/aimo-model && if [ "$LOCAL_EMBEDDINGS" = "true" ]; then \
    .venv/bin/python -c "import sys; sys.path.insert(0, '/tmp'); from model_spec import EMBEDDING_MODEL, EMBEDDING_REVISION; from sentence_transformers import SentenceTransformer; SentenceTransformer(EMBEDDING_MODEL, revision=EMBEDDING_REVISION, device='cpu', trust_remote_code=False)"; fi
COPY src/ src/
RUN uv pip install --no-deps -e .

# Independent worker image: durable queue, hosted Google models and agent tools.
# Legacy offline E5 support can be built with --build-arg LOCAL_EMBEDDINGS=true.
FROM runtime AS worker
ENV HF_HOME=/opt/aimo-model HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
COPY --from=worker-build /app/.venv /app/.venv
COPY --from=worker-build /opt/aimo-model /opt/aimo-model
EXPOSE 8001
CMD ["worker"]

# Independent frontend image: static React assets only; no application secrets.
FROM nginxinc/nginx-unprivileged:1.28-alpine@sha256:7377697a821c131a924a7105fafbe7414db4e9fcc77a6f08f776f33f141ec3f8 AS frontend
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=web-build /web/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
ENTRYPOINT ["nginx", "-g", "daemon off;"]
