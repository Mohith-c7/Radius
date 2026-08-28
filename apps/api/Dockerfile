FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10 \
    PYTHONPATH=/app/apps/api/src:/app/apps/worker/src:/app/packages/analysis/src:/app/packages/confidence/src:/app/packages/github/src:/app/packages/graph/src:/app/packages/parser/src:/app/packages/repository/src:/app/packages/shared/src:/app/packages/testing/src

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml alembic.ini ./
COPY infra/database ./infra/database

RUN python -m pip install --no-cache-dir .

COPY apps/api/src ./apps/api/src
COPY apps/worker/src ./apps/worker/src
COPY packages ./packages

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "radius_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
