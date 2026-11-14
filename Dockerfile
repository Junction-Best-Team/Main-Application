FROM node:24.6.0-bookworm-slim AS frontend
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12.12-slim-bookworm AS python-build
COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
# Pinned, untrusted-code-disabled model is cached during build, not fetched at pod startup.
ENV HF_HOME=/opt/aimo-model
COPY src/aimo/model_spec.py /tmp/model_spec.py
RUN .venv/bin/python -c "import sys; sys.path.insert(0, '/tmp'); from model_spec import EMBEDDING_MODEL, EMBEDDING_REVISION; from sentence_transformers import SentenceTransformer; SentenceTransformer(EMBEDDING_MODEL, revision=EMBEDDING_REVISION, device='cpu', trust_remote_code=False)"
COPY src/ src/
RUN uv sync --frozen --no-dev

FROM python:3.12.12-slim-bookworm
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH HF_HOME=/opt/aimo-model HF_HUB_OFFLINE=1 \
    PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 FRONTEND_DIST=/app/frontend/dist SECURE_COOKIES=true
RUN groupadd -g 10001 aimo && useradd -u 10001 -g aimo -M aimo
COPY --from=python-build /app/.venv /app/.venv
COPY --from=python-build /opt/aimo-model /opt/aimo-model
COPY src/ /app/src/
COPY migrations/ /app/migrations/
COPY --from=frontend /web/dist /app/frontend/dist
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["aimo"]
CMD ["serve"]
