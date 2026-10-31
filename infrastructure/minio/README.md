# MinIO

Artifacts (command logs, test output, reproduction reports) and the content-addressed blobs
of every file an agent writes are stored in the `forgeflow-artifacts` bucket. The API
creates the bucket on startup. Configure with `FORGEFLOW_S3_ENDPOINT`,
`FORGEFLOW_S3_ACCESS_KEY`, `FORGEFLOW_S3_SECRET_KEY` and `FORGEFLOW_S3_BUCKET`.
