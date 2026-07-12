# Auctor service — FastAPI + Mongo (Motor). Lean, no GPU/heavy-toolchain
# dependency (unlike ludexel-app's devkitARM base) — this is a plain Python
# service, so a slim official image is enough.

FROM python:3.12-slim AS build
WORKDIR /opt/auctor

RUN pip install --no-cache-dir uv

COPY pyproject.toml VERSION* /opt/auctor/
COPY service /opt/auctor/service
RUN uv pip install --system --no-cache -e .

FROM python:3.12-slim AS runtime
WORKDIR /opt/auctor

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY service /opt/auctor/service
COPY pyproject.toml /opt/auctor/

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

EXPOSE 8000
CMD ["uvicorn", "service.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
