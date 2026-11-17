FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    procps \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY requirements ./requirements
COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./

RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir --require-hashes --only-binary=:all: --no-deps -r requirements/build.txt -r requirements/runtime.txt \
    && pip install --no-cache-dir --no-deps --no-build-isolation . \
    && pip check

CMD ["python", "-m", "app.main"]
