# syntax=docker/dockerfile:1
# API / worker image. The worker drives the *host's* Docker daemon (mounted
# socket) to launch sandbox containers; it never runs candidate code itself.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends docker.io \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY sandbox ./sandbox
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install --no-cache-dir ".[postgres,llm]"

ENV CODEJUDGE_SANDBOX_BACKEND=docker
EXPOSE 8000
CMD ["uvicorn", "codejudge.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
