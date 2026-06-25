#!/usr/bin/env bash
# Seed the running Weaviate container with the chunked-docs fixture.
# Idempotent — the Python seeder skips chunk_ids already present.

set -euo pipefail

# Read WEAVIATE_URL from the environment, defaulting to http://localhost:8080
WEAVIATE_URL="${WEAVIATE_URL:-http://localhost:8080}"

echo "Seeding Weaviate inside the api container (WEAVIATE_URL: $WEAVIATE_URL)..."
docker compose exec -T api python api/seed_weaviate.py
echo "Weaviate seeding completed successfully."
