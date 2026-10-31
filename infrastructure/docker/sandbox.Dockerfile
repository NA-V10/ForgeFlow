# Image agent commands run in: no network (enforced by --network none), non-root, read-only rootfs.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git nodejs npm && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pytest ruff mypy \
 && useradd --uid 1000 --create-home agent
USER 1000:1000
WORKDIR /workspace
