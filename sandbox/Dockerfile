# syntax=docker/dockerfile:1
# Runner image for untrusted candidate code. Contains only the tooling needed
# to build, test, lint and scan Python submissions. The image is run with no
# network, a read-only root FS, dropped capabilities and cgroup limits.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# An optional build secret "ca" lets the image build behind a TLS-intercepting
# proxy:  docker build --secret id=ca,src=/path/to/ca.pem sandbox/
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; \
    pip install \
      "pytest==8.3.*" \
      "coverage==7.6.*" \
      "ruff==0.8.*" \
      "mypy==1.13.*" \
      "bandit==1.8.*" \
      "semgrep==1.97.*" \
      "setuptools<81" \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin runner

COPY semgrep-rules.yml /opt/codejudge/semgrep-rules.yml

# Semgrep and mypy want writable cache/home dirs; point them at tmpfs.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    SEMGREP_SEND_METRICS=off \
    SEMGREP_ENABLE_VERSION_CHECK=0 \
    MYPY_CACHE_DIR=/tmp/.mypy_cache

USER runner
WORKDIR /workspace
