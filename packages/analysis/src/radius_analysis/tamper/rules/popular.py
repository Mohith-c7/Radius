"""Small bundled list of well-known PyPI distributions and import-name aliases (offline).

This is deliberately short and hand-written: it only lets T012 skip packages everybody
knows and provides typosquat reference points. It is not a registry snapshot.
"""

from __future__ import annotations

POPULAR: frozenset[str] = frozenset(
    """
    requests urllib3 numpy pandas scipy matplotlib seaborn scikit-learn scikit-image
    pytest pytest-cov pytest-mock pytest-asyncio pytest-xdist pytest-timeout hypothesis
    coverage mypy ruff black flake8 pylint isort bandit tox nox pre-commit
    django flask fastapi starlette uvicorn gunicorn pydantic pydantic-settings sqlalchemy
    alembic psycopg2 psycopg2-binary psycopg asyncpg redis celery httpx aiohttp
    boto3 botocore click typer rich tqdm pyyaml toml tomli tomli-w jinja2 markupsafe
    cryptography pyjwt python-dateutil pytz tzdata attrs cattrs packaging setuptools wheel
    pip virtualenv six typing-extensions pillow opencv-python beautifulsoup4 lxml
    openai anthropic langchain tiktoken torch tensorflow transformers
    orjson ujson msgpack protobuf grpcio structlog loguru python-dotenv certifi idna
    charset-normalizer pygments docutils sphinx mkdocs tenacity retrying freezegun
    responses requests-mock factory-boy faker networkx tree-sitter regex
    """.split()
)

ALIASES: dict[str, str] = {
    "yaml": "pyyaml",
    "PIL": "pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "skimage": "scikit-image",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jwt": "pyjwt",
    "git": "gitpython",
    "attr": "attrs",
    "google": "protobuf",
    "psycopg2": "psycopg2-binary",
    "pytest_cov": "pytest-cov",
    "_pytest": "pytest",
    "pkg_resources": "setuptools",
    "OpenSSL": "pyopenssl",
    "serial": "pyserial",
    "markdown": "markdown",
}
