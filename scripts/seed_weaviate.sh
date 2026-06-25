#!/usr/bin/env bash
# Seed the running Weaviate container with the chunked-docs fixture.
#
# Idempotent — the Python seeder skips chunk_ids already present.

set -euo pipefail

# Run the seed inside the api container
docker compose exec -T api python seed_weaviate.py

echo "Weaviate database successfully seeded."
