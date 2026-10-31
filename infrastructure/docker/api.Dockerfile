FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git docker.io && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY packages ./packages
COPY apps/api ./apps/api
RUN pip install --no-cache-dir ./packages/version-engine ./packages/semantic-diff ./packages/risk-engine \
      ./packages/policy-engine ./packages/provenance ./packages/sandbox ./packages/merge-engine \
      "./apps/api[postgres,s3]"
EXPOSE 8000
CMD ["uvicorn", "forgeflow_api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
