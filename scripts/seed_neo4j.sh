#!/usr/bin/env bash
# Seed the running Neo4j container with the recipe fixture.
# Idempotent — `MERGE` and `CREATE CONSTRAINT IF NOT EXISTS` in seed.cypher
# mean repeat runs do not duplicate nodes.

set -euo pipefail

# Resolve repository root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Source .env file if it exists and variables aren't already set
if [ -f "$REPO_ROOT/.env" ]; then
  # Export variables while ignoring comments
  export $(grep -v '^#' "$REPO_ROOT/.env" | xargs)
fi

# Fallback defaults
NEO4J_USER="${NEO4J_USER:-neo4j}"
NEO4J_PASSWORD="${NEO4J_PASSWORD:-}"

if [ -z "$NEO4J_PASSWORD" ]; then
  echo "Error: NEO4J_PASSWORD environment variable is not set." >&2
  exit 1
fi

echo "Seeding Neo4j with api/seed.cypher..."
docker compose exec -T neo4j cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" < "$REPO_ROOT/api/seed.cypher"
echo "Neo4j seeding completed successfully."
